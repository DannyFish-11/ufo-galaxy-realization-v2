"""
core/cli_render.py — 精炼 CLI 渲染原语（按 clig.dev「human-first」标准）
=====================================================================

统一启动界面 banner 以下的所有输出。要点（对应 clig.dev 规则）：

- 默认安静：每个阶段折叠成【一行】``✓ 名称   值``；``-v`` 才展开逐项明细。
- 一套符号：``✓ 完成 · ◐ 进行中 · ⚠ 降级 · ✗ 失败``（不再混 ✅/❌/❎ 与 ╔═╗/════）。
- 一种分隔线：细线 ``──``。
- 对齐成列：按【显示宽度】(东亚字符算 2 格)对齐，彻底消除中文歪边。
- 颜色仅增强、可降级：非 TTY / NO_COLOR 时自动纯文本（复用 ascii_art.ansi_supported）。
- 结尾给「总结卡」：状态 + 关键值 + 降级项 + 下一步该点哪。

颜色/TTY 检测复用 ``core.ascii_art``，不重复造。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional, Sequence, Tuple

from core.ascii_art import Colors, ansi_supported

# ── 状态词汇（唯一一套）：name -> (glyph, color) ──
_STATUS: dict = {
    "ok": ("✓", Colors.GREEN),
    "doing": ("◐", Colors.CYAN),
    "warn": ("⚠", Colors.YELLOW),
    "fail": ("✗", Colors.RED),
    "info": ("·", Colors.BLUE),
}

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# 阶段行：标签列宽（显示格数）。中英混排在此列内左对齐，值列随后。
LABEL_COL = 22
RULE_WIDTH = 50


def _use_color() -> bool:
    return ansi_supported()


def display_width(s: str) -> int:
    """字符串的【终端显示宽度】：先剥 ANSI，东亚宽/全角字符算 2 格，其余 1 格。"""
    s = _ANSI_RE.sub("", s)
    w = 0
    for ch in s:
        if unicodedata.combining(ch):
            continue
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def pad_display(s: str, width: int, align: str = "left") -> str:
    """按显示宽度补空格到 ``width``（不截断；已超宽则原样返回）。"""
    pad = max(0, width - display_width(s))
    return (s + " " * pad) if align == "left" else (" " * pad + s)


def _c(text: str, color: str) -> str:
    return f"{color}{text}{Colors.ENDC}" if (_use_color() and color) else text


def glyph(status: str) -> str:
    g, color = _STATUS.get(status, _STATUS["info"])
    return _c(g, color)


def rule(width: int = RULE_WIDTH) -> None:
    """打印一条细分隔线。"""
    print("  " + _c("─" * width, Colors.DIM))


def phase(name: str, value: str = "", status: str = "ok") -> None:
    """折叠的阶段行（默认形态）：``  ✓ 名称              值``。

    图标占 2 显示格（图标 + 间隔），标签左对齐到 LABEL_COL，值用暗色跟随。
    """
    icon = pad_display(glyph(status), 2)
    label = pad_display(name, LABEL_COL)
    if value:
        print(f"  {icon}{label}  {_c(value, Colors.DIM)}")
    else:
        print(f"  {icon}{label}")


def detail(label: str, value: str = "", status: str = "ok") -> None:
    """展开模式(-v)下的子项行，缩进于阶段标题之下。"""
    icon = pad_display(glyph(status), 2)
    lab = pad_display(label, LABEL_COL)
    if value:
        print(f"      {icon}{lab}  {_c(value, Colors.DIM)}")
    else:
        print(f"      {icon}{lab}")


def section(title: str) -> None:
    """展开模式(-v)下的阶段小标题（细线之上）。"""
    print(f"\n  {_c(title, Colors.BOLD + Colors.CYAN)}")


def summary_card(
    *,
    title: str,
    state_ok: int,
    state_degraded: int,
    rows: Sequence[Tuple[str, str]],
    degraded: Optional[Sequence[Tuple[str, Optional[str]]]] = None,
    hints: Optional[Sequence[Tuple[str, str]]] = None,
) -> None:
    """结尾总结卡：状态 + 关键值 + 降级项 + 下一步。一屏看完。

    rows / hints 均为 (label, value) 列表，按显示宽度对齐。
    degraded 为 (名称, 专属修复建议) 列表——每一项各自的建议独立展示，而不是
    所有降级项共用一句话（"装后重跑即恢复"只对 Docker 这类场景成立；换成
    "模型没拉好"之类的降级，共用同一句会文不对题、误导用户该怎么修）。
    建议为 None 的项只展示名称，不编造建议。
    """
    key_w = max([display_width(k) for k, _ in list(rows) + list(hints or [])] + [4])
    print()
    rule()
    head = f"就绪 · {state_ok} 正常"
    if state_degraded:
        head += f" · {state_degraded} 降级"
    print(f"  {_c('✓', Colors.GREEN)} {_c(head, Colors.BOLD + Colors.GREEN)}" f"   {_c(title, Colors.DIM)}")
    print()
    for k, v in rows:
        print(f"    {_c(pad_display(k, key_w), Colors.CYAN)}   {v}")
    if degraded:
        parts = [f"{name} → {hint}" if hint else name for name, hint in degraded]
        joined = "  ·  ".join(parts)
        print(f"    {_c(pad_display('降级', key_w), Colors.YELLOW)}   " f"{_c(joined, Colors.DIM)}")
    if hints:
        print()
        for k, v in hints:
            print(f"    {_c(pad_display(k, key_w), Colors.DIM)}   {_c(v, Colors.DIM)}")
    rule()
