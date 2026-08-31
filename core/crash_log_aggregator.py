"""崩溃日志聚合器:把散落各处日志里的崩溃/致命片段汇到一个视图。

## 解决什么问题

崩溃排障最需要"一眼定位",而现实是:Electron 覆盖层崩在 ``electron.log``、
后端异常在 ``lumiv.log``、服务层在 ``windows_service.log``、节点崩在
``nodes/*.log``——用户真机出问题时要挨个翻,还得自己认哪几行才是崩溃。

本模块扫描统一日志根下的所有 ``*.log``,用崩溃特征匹配出**崩溃片段**
(traceback、fatal、crash、GPU process exited 等),带上下文汇总写入
``crashes/latest.log``;托盘"崩溃日志"一行直接打开它。

## 设计约束

- **只读汇总,不改动源日志**:源文件是各组件的事实记录,聚合器绝不改写/删除。
- **去重**:同一崩溃在多次聚合中只保留一份(按"来源+首行指纹"判重),
  避免 latest.log 被同一条崩溃刷屏——这正是所有者要求"删除重复日志"的一层。
- **有界**:每个源最多取最近 [MAX_BLOCKS_PER_SOURCE] 个崩溃块、每块最多
  [MAX_LINES_PER_BLOCK] 行,防止把 GB 级日志整个搬进来。
- **失败不致命**:任何源读取失败只记一行说明,不影响其它源与调用方。
"""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Iterator, NamedTuple

# 本模块**既是库也是脚本**(见文件末尾的 __main__ 守卫)。直接跑
# `python core/crash_log_aggregator.py` 时 sys.path[0] 是 core/ 而不是仓库根,
# 模块级的 `from core import ...` 会 ModuleNotFoundError。这里把仓库根补进去 ——
# 只在"没有包上下文"(即被当脚本跑)时补,正常 import 不受影响。
if __package__ in (None, ""):  # pragma: no cover - 只在直接执行时成立
    import os as _os
    import sys as _sys

    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

from core.fs_walk import walk_tree_files
from core.log_paths import crash_dir, crash_latest_path, log_root

__all__ = [
    "CrashBlock",
    "aggregate_crashes",
    "scan_source",
    "CRASH_PATTERNS",
]

#: 崩溃/致命特征总目录(大小写不敏感),供外部查阅本聚合器"认得哪些崩溃"。
#: 覆盖:Python traceback、通用 fatal/crash、Electron/Chromium 崩溃、
#: Windows 应用控制拦截(WinError 4551,真机出现过)、进程非零退出。
#:
#: 注意:命中本目录**不等于**就是崩溃锚点。真正的判定见 :func:`_is_crash_anchor`
#: —— 结构性特征(traceback、WinError…)可以出现在行内任意位置就算数;而
#: FATAL/CRITICAL/crash 这类普通英文词必须出现在日志的级别字段位置,
#: 否则一句提到 "CRITICAL" 的建议文案就会被当成崩溃(真机踩过)。
CRASH_PATTERNS: tuple[str, ...] = (
    r"Traceback \(most recent call last\)",
    r"\bFATAL\b",
    r"\bCRITICAL\b",
    r"\bcrash(ed|ing)?\b",
    r"Unhandled (exception|rejection)",
    r"未处理的异常",
    r"GPU process (exited|crashed)",
    r"renderer process (gone|crashed)",
    r"did-fail-load",
    r"WinError \d+",
    r"Segmentation fault",
    r"exited with code [1-9]",
)

#: 只要出现就足以判定崩溃的**结构性**特征——它们本身就是崩溃现场的形状,
#: 不可能出现在正常叙述里。
_STRUCTURAL_RE = re.compile(
    "|".join(
        (
            r"Traceback \(most recent call last\)",
            r"Unhandled (exception|rejection)",
            r"未处理的异常",
            r"GPU process (exited|crashed)",
            r"renderer process (gone|crashed)",
            r"did-fail-load",
            r"WinError \d+",
            r"Segmentation fault",
            r"exited with code [1-9]",
        )
    ),
    re.IGNORECASE,
)

#: FATAL/CRITICAL/crash 这类**普通英文词**只有出现在日志的"级别字段"位置才算数
#: (``... | CRITICAL | ...``、``CRITICAL:``、行首)。
#:
#: 为什么必须加这道闸(真机实证):预检输出里有一句纯建议文案——
#: "GALAXY_REQUIRE_API_TOKEN=true makes a missing token **CRITICAL** even with
#: auth off" ——它被 ``\bCRITICAL\b`` 命中,于是聚合视图把一条建议当成崩溃锚点,
#: 真正的崩溃反倒被当作它的"上下文"吞进块里;而同一个崩溃在另一个日志里锚在
#: 正确的 ``| CRITICAL |`` 行上,两边指纹不同 → **同一个崩溃出现了两次**。
_LEVEL_TOKEN_RE = re.compile(
    r"(?:^|\||\[)\s*(?:FATAL|CRITICAL|CRASH(?:ED|ING)?)\b\s*(?:\||:|\])",
    re.IGNORECASE,
)

#: 级别字段明确是 INFO/DEBUG/TRACE 的行,**永远不做崩溃锚点**。
#:
#: 真机实证:``| INFO | 注册安全规则: 高度限制检查 (critical)`` 和
#: ``| INFO | Crash aggregation: 4 block(s) -> ...``(聚合器自己的记账行!)
#: 都曾被判成崩溃。一条 INFO 按定义就不是崩溃记录,这条规则同时也用来判定
#: "崩溃现场到哪儿结束"——日志回到正常流水,现场就结束了。
_BENIGN_LEVEL_RE = re.compile(r"\|\s*(?:INFO|DEBUG|TRACE)\s*\|", re.IGNORECASE)


def _is_crash_anchor(line: str) -> bool:
    """该行是否可以作为崩溃块的起点。"""
    if _BENIGN_LEVEL_RE.search(line):
        return False
    return bool(_STRUCTURAL_RE.search(line) or _LEVEL_TOKEN_RE.search(line))


#: 单个崩溃块最多保留的行数(含起始行)。traceback 往往很长,给足。
MAX_LINES_PER_BLOCK = 40

#: 非 traceback 类(单行错误)崩溃块保留的后续上下文行数。
#:
#: 真机实证:此前不分类型一律取 40 行,结果一条 ``nats-server.zip 解压失败``
#: 后面跟了 39 行毫不相干的 INFO 流水(节点启动、健康检查…),聚合视图里
#: 真正有用的就头一行。单行错误给少量上下文即可。
CONTEXT_LINES_SINGLE = 6

#: 每个源日志最多提取的崩溃块数(取最近的)。
MAX_BLOCKS_PER_SOURCE = 5

#: 扫描单个源日志时最多读取的尾部字节(避免读取超大日志的历史部分)。
MAX_TAIL_BYTES = 2 * 1024 * 1024  # 2 MB


class CrashBlock(NamedTuple):
    """一个崩溃片段。

    :param source:      来源日志文件名(相对日志根)。
    :param first_line:  触发匹配的那一行(去尾空白)。
    :param lines:       崩溃块全文(含起始行与其后的上下文)。
    :param fingerprint: 去重指纹(来源 + 首行归一化后的哈希)。
    """

    source: str
    first_line: str
    lines: list[str]
    fingerprint: str


def _fingerprint(source: str, first_line: str) -> str:
    """按**崩溃内容本身**生成去重指纹(刻意不含来源名)。

    两层归一化保证"同一个崩溃只出现一次":

    1. 首行里的时间戳/行号/内存地址等数字被归一化为 ``#``——否则同一崩溃每次
       时间不同就会被当成新条目重复写入;
    2. **不把 source 计入指纹**——同一崩溃常被多个组件各记一份(如启动器与
       服务层都记 Electron 崩溃),计入来源会让同一件事在聚合视图里出现多条。
       合并后由 :class:`CrashBlock` 的 ``sources`` 字段列出全部来源,信息不丢。

    :param source: 仅保留形参以兼容调用点,不参与指纹计算。
    """
    del source  # 刻意不参与:跨来源的同一崩溃必须合并为一条
    normalized = re.sub(r"\d+", "#", first_line.strip())
    return hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest()[:16]


def _read_tail_lines(path: Path) -> list[str]:
    """读取日志尾部(最多 [MAX_TAIL_BYTES]),返回行列表。"""
    size = path.stat().st_size
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        if size > MAX_TAIL_BYTES:
            fh.seek(size - MAX_TAIL_BYTES)
            fh.readline()  # 丢弃可能被截断的半行
        return fh.read().splitlines()


def _collect_block(lines: list[str], idx: int) -> list[str]:
    """从锚点行 ``idx`` 起,截出崩溃现场。

    两条收尾规则,都是为了让块里**只有现场**、没有流水:

    1. traceback 类给到 [MAX_LINES_PER_BLOCK] 行(调用栈本来就长);
       单行错误类只给 [CONTEXT_LINES_SINGLE] 行上下文。
    2. 一旦遇到级别为 INFO/DEBUG/TRACE 的行,说明日志已经回到正常流水,
       崩溃现场就此结束——立即收尾,不再往下吞。
    """
    limit = MAX_LINES_PER_BLOCK if _STRUCTURAL_RE.search(lines[idx]) else 1 + CONTEXT_LINES_SINGLE
    block = [lines[idx]]
    for nxt in lines[idx + 1 : idx + limit]:
        if _BENIGN_LEVEL_RE.search(nxt):
            break
        block.append(nxt)
    return block


def scan_source(path: Path, root: Path | None = None) -> list[CrashBlock]:
    """扫描单个日志文件,提取其中的崩溃块(最近 [MAX_BLOCKS_PER_SOURCE] 个)。"""
    root = root or log_root()
    try:
        source = str(path.relative_to(root))
    except ValueError:
        source = path.name

    try:
        lines = _read_tail_lines(path)
    except OSError as exc:
        return [
            CrashBlock(
                source=source,
                first_line=f"(无法读取该日志: {exc})",
                lines=[f"(无法读取该日志: {exc})"],
                fingerprint=_fingerprint(source, "unreadable"),
            )
        ]

    blocks: list[CrashBlock] = []
    idx = 0
    total = len(lines)
    while idx < total:
        if _is_crash_anchor(lines[idx]):
            block = _collect_block(lines, idx)
            blocks.append(
                CrashBlock(
                    source=source,
                    first_line=lines[idx].rstrip(),
                    lines=[ln.rstrip() for ln in block],
                    fingerprint=_fingerprint(source, lines[idx]),
                )
            )
            idx += len(block)
        else:
            idx += 1

    return blocks[-MAX_BLOCKS_PER_SOURCE:]


def _iter_source_logs(root: Path) -> Iterator[Path]:
    """遍历日志根下所有 ``*.log``,跳过崩溃专区自身(避免自我递归聚合)。"""
    crashes = crash_dir().resolve()
    # 日志目录一直在被写入与轮转,遍历途中子目录消失是常态而不是异常。
    for path in walk_tree_files(root, "*.log"):
        if crashes in path.resolve().parents or path.resolve().parent == crashes:
            continue
        yield path


def aggregate_crashes(root: Path | None = None) -> tuple[Path, int]:
    """扫描全部日志、汇总崩溃块到 ``crashes/latest.log``。

    :returns: ``(聚合文件路径, 本次写入的崩溃块数)``。

    去重语义:已经出现在当前 ``latest.log`` 里的指纹不再重复写入;文件按
    "最新一次聚合完整重写"的方式生成,故不会无限增长。
    """
    root = root or log_root()
    target = crash_latest_path()

    # 同一崩溃(指纹相同)只保留首次出现的正文,其余来源并入 sources 列表——
    # 既满足"删除重复"的要求,又不丢失"这条崩溃被哪些组件记录过"的信息。
    merged: dict[str, CrashBlock] = {}
    extra_sources: dict[str, list[str]] = {}
    for log_file in _iter_source_logs(root):
        for block in scan_source(log_file, root):
            existing = merged.get(block.fingerprint)
            if existing is None:
                merged[block.fingerprint] = block
                extra_sources[block.fingerprint] = [block.source]
            elif block.source not in extra_sources[block.fingerprint]:
                extra_sources[block.fingerprint].append(block.source)
    collected: list[CrashBlock] = list(merged.values())

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    out: list[str] = [
        "=" * 72,
        f"Galaxy 崩溃日志聚合视图 · 生成于 {ts}",
        f"日志根: {root}",
        "=" * 72,
        "",
    ]

    if not collected:
        out.append("✅ 未发现崩溃记录 —— 所有日志中都没有匹配到崩溃/致命错误特征。")
        out.append("")
        out.append("(本文件由 core/crash_log_aggregator.py 自动生成;源日志保持原样不被改动。)")
    else:
        out.append(f"共发现 {len(collected)} 处崩溃(相同崩溃已跨来源合并去重):")
        out.append("")
        for i, block in enumerate(collected, 1):
            srcs = extra_sources.get(block.fingerprint, [block.source])
            src_label = ", ".join(srcs)
            if len(srcs) > 1:
                src_label += f"  (同一崩溃被 {len(srcs)} 个组件记录)"
            out.append("-" * 72)
            out.append(f"[{i}] 来源: {src_label}    指纹: {block.fingerprint}")
            out.append("-" * 72)
            out.extend(block.lines)
            out.append("")

    target.write_text("\n".join(out) + "\n", encoding="utf-8")
    return target, len(collected)


def main() -> int:
    """命令行入口:``python -m core.crash_log_aggregator``。"""
    path, count = aggregate_crashes()
    print(f"崩溃聚合完成: {count} 处 -> {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
