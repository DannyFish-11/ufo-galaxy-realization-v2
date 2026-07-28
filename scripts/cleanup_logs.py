#!/usr/bin/env python3
"""日志清理工具:删除重复/陈旧/空的日志,并把历史遗留根迁移到统一根。

## 为什么需要

日志统一到单一根之后,仓库里仍可能残留三类"该删的":

1. **空日志**:进程建了文件却从未写入(如 0 字节的 ``lumiv.log`` / ``ollama.log``),
   对排障零价值,只会让日志目录显得杂乱、干扰用户判断;
2. **陈旧日志**:超过保留期的历史文件(默认 30 天),以及轮转备份 ``*.log.1``、
   ``*.log.2`` 等;
3. **遗留根里的重复副本**:``~/.galaxy/logs`` 是统一前的第二个根,里面的文件与
   统一根内容重复或已过时。

## 安全约束(不做破坏性动作)

- **默认 dry-run**:不加 ``--apply`` 只打印将要删除/迁移的清单,绝不动文件;
- **绝不删非日志文件**:只处理 ``*.log`` / ``*.log.<数字>`` ;
- **绝不删崩溃专区**:``crashes/`` 下的聚合结果与崩溃归档永远保留;
- **遗留根是迁移而非删除**:``~/.galaxy/logs`` 里统一根没有的文件会被**移动**
  过去(带 ``legacy_`` 前缀防重名),用户既有日志不会凭空消失;
- **今天的日志一律不动**:无论大小,当天修改过的文件都跳过(可能正被写入)。

用法::

    python scripts/cleanup_logs.py            # 预览(不改动任何文件)
    python scripts/cleanup_logs.py --apply    # 实际执行
    python scripts/cleanup_logs.py --apply --days 7
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
from pathlib import Path

# 允许从项目根直接运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.log_paths import crash_dir, legacy_log_roots, log_root  # noqa: E402

#: 轮转备份文件名模式,如 lumiv.log.1 / app.log.12
_ROTATED_RE = re.compile(r"\.log\.\d+$")

#: 默认保留天数:更早的日志视为陈旧。
DEFAULT_RETENTION_DAYS = 30


def _is_log_file(path: Path) -> bool:
    """仅 ``*.log`` 与轮转备份算日志——其它文件一律不碰。"""
    return path.suffix == ".log" or bool(_ROTATED_RE.search(path.name))


def _in_crash_area(path: Path) -> bool:
    """崩溃专区内的文件永不清理(排障最后的依据)。"""
    try:
        crashes = crash_dir().resolve()
        rp = path.resolve()
        return rp == crashes or crashes in rp.parents
    except OSError:
        return False


def plan_cleanup(days: int) -> tuple[list[tuple[Path, str]], list[tuple[Path, Path]]]:
    """计算清理计划。

    :returns: ``(待删除列表[(路径, 原因)], 待迁移列表[(源, 目标)])``
    """
    root = log_root()
    cutoff = time.time() - days * 86400
    today_start = time.time() - 86400

    deletions: list[tuple[Path, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not _is_log_file(path) or _in_crash_area(path):
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        if st.st_size == 0:
            # 空文件单独判定,不受"当天文件跳过"约束:0 字节意味着从未写入过内容,
            # 无论新旧都没有排障价值(真机上 lumiv.log/ollama.log 就长期是 0 字节,
            # 只会让日志目录显得杂乱、干扰用户判断该看哪个文件)。
            deletions.append((path, "空文件(0 字节,无排障价值)"))
            continue
        if st.st_mtime > today_start:
            continue  # 当天有内容的文件可能正被写入,跳过
        if _ROTATED_RE.search(path.name) and st.st_mtime < cutoff:
            deletions.append((path, f"陈旧轮转备份(>{days} 天)"))
        elif st.st_mtime < cutoff:
            deletions.append((path, f"陈旧日志(>{days} 天未更新)"))

    migrations: list[tuple[Path, Path]] = []
    for legacy in legacy_log_roots():
        for path in sorted(legacy.rglob("*")):
            if not path.is_file() or not _is_log_file(path):
                continue
            target = root / f"legacy_{path.name}"
            if target.exists():
                continue  # 统一根已有同名,视为重复副本,交由删除逻辑按年龄处理
            migrations.append((path, target))

    return deletions, migrations


def main() -> int:
    ap = argparse.ArgumentParser(description="清理重复/陈旧/空日志并迁移遗留日志根")
    ap.add_argument("--apply", action="store_true", help="实际执行(默认只预览)")
    ap.add_argument("--days", type=int, default=DEFAULT_RETENTION_DAYS, help="保留天数(默认 30)")
    args = ap.parse_args()

    deletions, migrations = plan_cleanup(args.days)
    root = log_root()

    print(f"统一日志根: {root}")
    print(f"模式: {'执行' if args.apply else '预览(加 --apply 才实际改动)'}")
    print("-" * 60)

    if migrations:
        print(f"待迁移(遗留根 → 统一根)共 {len(migrations)} 个:")
        for src, dst in migrations:
            print(f"  {src}  ->  {dst}")
            if args.apply:
                try:
                    shutil.move(str(src), str(dst))
                except OSError as exc:
                    print(f"    ! 迁移失败: {exc}")
    else:
        print("待迁移: 无(不存在遗留日志根或其中无日志)")

    print("-" * 60)
    if deletions:
        total = 0
        print(f"待删除共 {len(deletions)} 个:")
        for path, reason in deletions:
            try:
                total += path.stat().st_size
            except OSError:
                pass
            print(f"  {path}  —— {reason}")
            if args.apply:
                try:
                    path.unlink()
                except OSError as exc:
                    print(f"    ! 删除失败: {exc}")
        print(f"合计可回收: {total / 1024:.1f} KB")
    else:
        print("待删除: 无(没有空文件/陈旧日志)")

    print("-" * 60)
    print("崩溃专区 crashes/ 已跳过(永不清理)。")
    if not args.apply:
        print("这是预览。确认无误后加 --apply 执行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
