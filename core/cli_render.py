"""
core/cli_render.py — 精炼 CLI 渲染原语（按 clig.dev「human-first」标准）
=====================================================================

统一启动界面 banner 以下的所有输出。要点（对应 clig.dev 规则）：

- 默认安静：每个阶段折叠成【一行】``✓ 名称   值``；``-v`` 才展开逐项明细。
- 一套符号：``✓ 完成 · ◐ 进行中 · ⚠ 降级 · ✗ 失败``（不再混 ✅/❌/❎ 与 ╔═╗/════）。
- 一种分隔线：细线 ``──``，且**与横幅同一道 24-bit 渐变**（见下）。
- 对齐成列：按【显示宽度】(东亚字符算 2 格)对齐，彻底消除中文歪边。
- 颜色仅增强、可降级：非 TTY / ``NO_COLOR`` 时自动纯文本。
- 结尾给「总结卡」：状态 + 关键值 + 降级项 + 下一步该点哪。

版面几何与渐变都来自 ``core.ascii_art``，本模块不重复定义
--------------------------------------------------------
此前本模块自带 ``LABEL_COL=22`` / ``RULE_WIDTH=50`` / ``display_width`` /
``pad_display``，而 ``ascii_art`` 那边另有一套（``print_status_row`` 用
``str.ljust``、章节线 60 宽平 CYAN）。同一屏里于是出现三种线宽、三种线条着色、
两套填充语义。现在几何常量与显示宽度函数全部从 ``ascii_art`` 导入，横线走
``ascii_art.gradient_rule`` —— 颜色与横幅同源，右边缘与横幅同列。

模块级名字（``LABEL_COL`` / ``RULE_WIDTH`` / ``display_width`` / ``pad_display``）
继续导出，老调用点不用改。
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from core.ascii_art import (
    CONTENT_INDENT,
    ICON_COL,
    LABEL_COL,
    RULE_WIDTH,
    VALUE_COL,
    Colors,
    ansi_supported,
    display_width,
    gradient_rule,
    pad_display,
)

# ── 状态词汇（唯一一套）：name -> (glyph, color) ──
_STATUS: dict = {
    "ok": ("✓", Colors.GREEN),
    "doing": ("◐", Colors.CYAN),
    "warn": ("⚠", Colors.YELLOW),
    "fail": ("✗", Colors.RED),
    "info": ("·", Colors.BLUE),
}

#: 再导出，供仍按老路径 import 的调用点使用（本模块不再自己定义）。
__all__ = [
    "CONTENT_INDENT",
    "LABEL_COL",
    "RULE_WIDTH",
    "VALUE_COL",
    "display_width",
    "pad_display",
    "glyph",
    "rule",
    "phase",
    "detail",
    "section",
    "summary_card",
]


def _use_color() -> bool:
    return ansi_supported()


def _c(text: str, color: str) -> str:
    return f"{color}{text}{Colors.ENDC}" if (_use_color() and color) else text


def glyph(status: str) -> str:
    g, color = _STATUS.get(status, _STATUS["info"])
    return _c(g, color)


def rule(width: int = RULE_WIDTH) -> None:
    """打印一条细分隔线 —— **与横幅同一道 24-bit 渐变**。

    改造点：此前是 ``"  " + DIM("─" * 50)``，即平淡灰、宽 50，比横幅短 10 列、
    右边缘悬空。现在宽度取 :data:`RULE_WIDTH`\\ （= 横幅宽 − 缩进 = 58），
    着色交给 ``ascii_art.gradient_rule``：它按**屏幕列**取色，所以这条线拿到的
    正是横幅在第 2..59 列的那一段颜色。两者是同一道渐变的不同片段，而不是
    "看起来差不多的两种颜色"。

    非 TTY / ``NO_COLOR`` 时自动降级为纯字符，缩进与宽度不变（纯文本下依然对齐）。
    """
    print(gradient_rule(width))


#: 子项行的缩进（格）：比阶段行深一个"图标 + 间隔"的量，形成可见的层级。
#: 写成算式而不是字面量 6，是为了让它跟着几何常量走。
_DETAIL_INDENT = CONTENT_INDENT + ICON_COL + 2

#: 子项的标签列宽 —— **由值列反推**，使子项的值与阶段行的值落在同一列。
#:
#: 此前子项固定用 LABEL_COL(22)，于是它的值列 = 6 + 2 + 22 + 2 = **32**，
#: 而阶段行的值列是 **28**：``-v`` 一展开，所有值就整体右移 4 格，同一屏里
#: 出现两条值列。缩进表达层级、值列保持对齐，两者不该互相牵连。
_DETAIL_LABEL_COL = max(1, VALUE_COL - _DETAIL_INDENT - ICON_COL - 2)


def phase(name: str, value: str = "", status: str = "ok") -> None:
    """折叠的阶段行（默认形态）：``  ✓ 名称              值``。

    列位全部由 ``ascii_art`` 的几何常量决定，不再写字面量：

        缩进 CONTENT_INDENT(2) + 图标 ICON_COL(2) + 标签 LABEL_COL(22) + 2
        ⇒ 值列起始 = VALUE_COL(28)

    ``ascii_art.print_status_row`` 用的是同一组常量，所以两套打印器输出的
    对勾列、标签列、值列**逐列一致** —— 这是"跨模块严格对齐"的实现方式。
    """
    icon = pad_display(glyph(status), ICON_COL)
    label = pad_display(name, LABEL_COL)
    head = f"{' ' * CONTENT_INDENT}{icon}{label}"
    if value:
        print(f"{head}  {_c(value, Colors.DIM)}")
    else:
        print(head)


def detail(label: str, value: str = "", status: str = "ok") -> None:
    """展开模式(-v)下的子项行，缩进于阶段标题之下。

    **值列与阶段行同列**（都是 :data:`~core.ascii_art.VALUE_COL`）：缩进负责
    表达层级，值列负责对齐，两者互不牵连。见 :data:`_DETAIL_LABEL_COL`。
    """
    icon = pad_display(glyph(status), ICON_COL)
    lab = pad_display(label, _DETAIL_LABEL_COL)
    head = f"{' ' * _DETAIL_INDENT}{icon}{lab}"
    if value:
        print(f"{head}  {_c(value, Colors.DIM)}")
    else:
        print(head)


def section(title: str) -> None:
    """展开模式(-v)下的阶段小标题（细线之上）。"""
    print(f"\n{' ' * CONTENT_INDENT}{_c(title, Colors.BOLD + Colors.CYAN)}")


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
    # 卡内的键列宽按内容算（卡是一块紧凑的键值表，不必拉到 VALUE_COL —— 那会
    # 让"网关"这种短标签后面留一大片空）。但缩进必须由几何常量派生，不能再写
    # 字面量 2/4，否则下一次调整缩进时这里又会掉队。
    head_indent = " " * CONTENT_INDENT
    body_indent = " " * (CONTENT_INDENT * 2)
    key_w = max([display_width(k) for k, _ in list(rows) + list(hints or [])] + [4])
    print()
    rule()
    head = f"就绪 · {state_ok} 正常"
    if state_degraded:
        head += f" · {state_degraded} 降级"
    print(f"{head_indent}{_c('✓', Colors.GREEN)} {_c(head, Colors.BOLD + Colors.GREEN)}   {_c(title, Colors.DIM)}")
    print()
    for k, v in rows:
        print(f"{body_indent}{_c(pad_display(k, key_w), Colors.CYAN)}   {v}")
    if degraded:
        parts = [f"{name} → {hint}" if hint else name for name, hint in degraded]
        joined = "  ·  ".join(parts)
        print(f"{body_indent}{_c(pad_display('降级', key_w), Colors.YELLOW)}   {_c(joined, Colors.DIM)}")
    if hints:
        print()
        for k, v in hints:
            print(f"{body_indent}{_c(pad_display(k, key_w), Colors.DIM)}   {_c(v, Colors.DIM)}")
    rule()
