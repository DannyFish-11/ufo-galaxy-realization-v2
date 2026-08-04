"""启动界面的版面契约：一套几何、一道渐变、跨模块严格同列。

背景（实测，不是推测）
----------------------
统一之前，同一屏启动输出里存在：

* **三种宽度** —— 横幅 60、``print_section_header`` 60、``cli_render.rule`` **50**；
* **三种线条着色** —— 横幅 24-bit 渐变、章节线平 CYAN、细线平 DIM；
* **两套填充语义** —— ``print_status_row`` 用 ``str.ljust``（按码点）、
  ``cli_render`` 用显示宽度。

最后那条是实打实的错位。实测：``"环境检查".ljust(22)`` 的显示宽度是 **26**、
``"AI 大脑"`` 是 **24**、``"三态覆盖层"`` 是 **27**，而 ``pad_display(..., 22)``
恒为 22 —— 两套打印器在同一屏里各自缩进，中文标签差 2~5 列。

这个文件钉住统一后的性质，且每条都直接对应一个当初的具体缺陷。
"""

from __future__ import annotations

import contextlib
import io

import pytest

from core import ascii_art as A
from core import cli_render as R

# ---------------------------------------------------------------------------
# 0. 几何只有一份
# ---------------------------------------------------------------------------


class TestSingleSourceOfGeometry:
    def test_cli_render_reuses_ascii_art_constants(self) -> None:
        """``cli_render`` 不得自己再定义一套宽度/列位。"""
        assert R.LABEL_COL is A.LABEL_COL
        assert R.RULE_WIDTH is A.RULE_WIDTH
        assert R.CONTENT_INDENT is A.CONTENT_INDENT
        assert R.VALUE_COL is A.VALUE_COL

    def test_display_width_helpers_are_the_same_object(self) -> None:
        """``display_width`` / ``pad_display`` 全仓只能有一份实现。

        它们此前住在 ``cli_render``，而 ``ascii_art`` 那边用 ``str.ljust`` ——
        两套填充语义并存正是中文错位的根源。
        """
        assert R.display_width is A.display_width
        assert R.pad_display is A.pad_display

    def test_rule_width_is_derived_from_banner(self) -> None:
        """横线宽度必须是**算出来的**，右边缘与横幅同列；不许是独立字面量。"""
        assert A.RULE_WIDTH == A.BANNER_WIDTH - A.CONTENT_INDENT
        assert A.CONTENT_INDENT + A.RULE_WIDTH == A.BANNER_WIDTH

    def test_value_col_is_derived(self) -> None:
        assert A.VALUE_COL == A.CONTENT_INDENT + A.ICON_COL + A.LABEL_COL + 2


# ---------------------------------------------------------------------------
# 1. 横幅不许被改动（这是本次改造的底线）
# ---------------------------------------------------------------------------


class TestBannerIsUntouched:
    def test_banner_is_uniform_width(self) -> None:
        lines = A.GALAXY_BANNER.split("\n")
        assert len({A.display_width(ln) for ln in lines}) == 1
        assert A.display_width(lines[0]) == A.BANNER_WIDTH

    def test_every_banner_char_is_one_column(self) -> None:
        """按屏幕列做渐变之所以与旧实现逐字节一致，前提就是这一条。

        横幅用的框线字符（═║╔╗╚╝）与 █ 的 east_asian_width 都是 'A'（ambiguous），
        按本仓库的判据算 1 格。若将来往横幅里塞了宽字符，这条会红 —— 那时
        必须重新核对渐变，而不是想当然。
        """
        for line in A.GALAXY_BANNER.split("\n"):
            assert len(line) == A.display_width(line), f"横幅出现了非 1 格字符：{line!r}"

    def test_colorize_line_matches_column_based_gradient(self) -> None:
        """``_colorize_line``（横幅用）必须等价于 col_offset=0 的 gradient_text。"""
        for line in A.GALAXY_BANNER.split("\n"):
            assert A._colorize_line(line) == A.gradient_text(line, col_offset=0, scale=A.BANNER_WIDTH, bold=True)


# ---------------------------------------------------------------------------
# 2. 线条统一成横幅的渐变
# ---------------------------------------------------------------------------


class TestRulesShareTheBannerGradient:
    def test_rule_colors_are_a_slice_of_the_banner_gradient(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """缩进 2 格的横线，其每一列的颜色必须等于横幅在同一列的颜色。

        这是"统一成横幅渐变色"的**可验证**含义：不是"配色相近"，而是同一道
        渐变的同一列。按字符序号取色（旧式做法）会把整条渐变压进 58 格，与
        横幅的第 2..59 列对不上 —— 那样这条测试会红。
        """
        monkeypatch.setattr(A, "ansi_supported", lambda: True)
        rule_line = A.gradient_rule()
        banner_line = A.gradient_text("─" * A.BANNER_WIDTH, col_offset=0, scale=A.BANNER_WIDTH, bold=False)

        rule_rgb = _rgb_sequence(rule_line)
        banner_rgb = _rgb_sequence(banner_line)
        # 横线从第 CONTENT_INDENT 列开始，应与横幅同列起的颜色逐个相等
        assert rule_rgb == banner_rgb[A.CONTENT_INDENT :], "横线的颜色不是横幅同列的颜色"

    def test_rule_spans_to_the_banner_right_edge(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(A, "ansi_supported", lambda: False)
        line = A.gradient_rule()
        assert A.display_width(line) == A.BANNER_WIDTH, "横线右边缘没有与横幅对齐"
        assert line.startswith(" " * A.CONTENT_INDENT)

    def test_section_header_line_uses_the_gradient_not_flat_cyan(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """章节线此前是平 CYAN，与横幅的渐变割裂。"""
        monkeypatch.setattr(A, "ansi_supported", lambda: True)
        A.print_section_header("服务启动")
        out = capsys.readouterr().out
        assert "38;2;" in out, "章节线没有 24-bit 渐变"
        # 平 CYAN 的老实现会出现 Colors.CYAN 紧跟 ═；渐变实现不会
        assert f"{A.Colors.CYAN}═" not in out, "章节线仍是平 CYAN"

    def test_gradient_endpoints_match_the_anchor_colors(self) -> None:
        """自证：渐变两端必须真的是首尾锚点色，否则上面几条比的是两个错值。"""
        assert A._interp_rgb(0.0) == A._ANCHOR_COLORS[0]
        assert A._interp_rgb(1.0) == A._ANCHOR_COLORS[-1]


def _rgb_sequence(text: str) -> list:
    """从带 ANSI 的字符串里抽出逐字符的 (r,g,b) 序列。"""
    import re

    return [tuple(int(x) for x in m) for m in re.findall(r"\x1b\[38;2;(\d+);(\d+);(\d+)m", text)]


# ---------------------------------------------------------------------------
# 3. 跨模块严格同列（本次改造要修的那个实际错位）
# ---------------------------------------------------------------------------

_LABELS = ["Python", "环境检查", "AI 大脑", "Tailscale", "三态覆盖层", "NATS"]


class TestCrossPrinterAlignment:
    def test_ljust_would_have_misaligned_cjk(self) -> None:
        """自证：这条错位是真的，不是假想的。

        没有它，下面那条"两套打印器同列"可能只是碰巧成立（比如两边都错得
        一样多），读者也无从知道当初到底坏在哪。
        """
        offenders = [lb for lb in _LABELS if A.display_width(lb.ljust(A.LABEL_COL)) != A.LABEL_COL]
        assert offenders, "样例里没有中文标签，这条自证就失去意义了"
        for lb in offenders:
            assert A.display_width(A.pad_display(lb, A.LABEL_COL)) == A.LABEL_COL

    @pytest.mark.parametrize("label", _LABELS)
    def test_both_printers_put_the_value_at_the_same_column(self, label: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """``print_status_row`` 与 ``cli_render.phase`` 的值列必须逐列一致。"""
        monkeypatch.setattr(A, "ansi_supported", lambda: False)
        marker = "X_VALUE_X"

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            A.print_status_row(label, marker, "success")
        row_line = buf.getvalue().rstrip("\n")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            R.phase(label, marker, "ok")
        phase_line = buf.getvalue().rstrip("\n")

        row_col = A.display_width(row_line[: row_line.index(marker)])
        phase_col = A.display_width(phase_line[: phase_line.index(marker)])
        assert row_col == phase_col == A.VALUE_COL, (
            f"标签 {label!r} 的值列不一致：print_status_row={row_col} "
            f"cli_render.phase={phase_col} 期望={A.VALUE_COL}"
        )

    @pytest.mark.parametrize("label", _LABELS)
    def test_detail_value_shares_the_phase_value_column(self, label: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """``-v`` 展开后，子项的值必须与阶段行的值**同列**。

        此前子项固定用 LABEL_COL(22)，值列因此是 6+2+22+2=32，而阶段行是 28
        —— 一按 ``-v``，整屏的值就右移 4 格，同屏出现两条值列。缩进表达层级、
        值列负责对齐，两者不该互相牵连。
        """
        monkeypatch.setattr(A, "ansi_supported", lambda: False)
        marker = "X_VALUE_X"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            R.phase(label, marker)
            R.detail(label, marker)
        parent, child = [ln for ln in buf.getvalue().split("\n") if ln.strip()]
        assert A.display_width(parent[: parent.index(marker)]) == A.VALUE_COL
        assert A.display_width(child[: child.index(marker)]) == A.VALUE_COL, "子项的值列与阶段行不同列"

    def test_detail_is_still_visibly_nested(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """值列对齐了，但层级仍要看得出来：子项的缩进必须比阶段行深。"""
        monkeypatch.setattr(A, "ansi_supported", lambda: False)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            R.phase("父项", "v")
            R.detail("子项", "v")
        parent, child = [ln for ln in buf.getvalue().split("\n") if ln.strip()]
        parent_indent = A.display_width(parent) - A.display_width(parent.lstrip())
        child_indent = A.display_width(child) - A.display_width(child.lstrip())
        assert child_indent > parent_indent, "子项没有比阶段行更深的缩进，层级消失了"


# ---------------------------------------------------------------------------
# 4. 颜色可降级（NO_COLOR 此前是个说谎的注释）
# ---------------------------------------------------------------------------


class TestColorDegradation:
    def test_no_color_env_disables_color(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """https://no-color.org/ ：变量【存在】即禁用，哪怕是空串。"""
        monkeypatch.setattr("sys.stdout.isatty", lambda: True, raising=False)
        monkeypatch.setenv("NO_COLOR", "")
        assert A.ansi_supported() is False

    def test_galaxy_no_color_env_disables_color(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stdout.isatty", lambda: True, raising=False)
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("GALAXY_NO_COLOR", "1")
        assert A.ansi_supported() is False

    def test_print_status_row_honours_ansi_support(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """此前它只看 ``use_color`` 参数，不查终端能力 —— 管道里会混进转义码。"""
        monkeypatch.setattr(A, "ansi_supported", lambda: False)
        A.print_status_row("Python", "3.11", "success")
        assert "\x1b[" not in capsys.readouterr().out

    def test_rule_degrades_to_plain_but_keeps_geometry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """纯文本下线条也必须保持宽度与缩进，否则降级即错位。"""
        monkeypatch.setattr(A, "ansi_supported", lambda: False)
        plain = A.gradient_rule()
        assert "\x1b[" not in plain
        assert A.display_width(plain) == A.BANNER_WIDTH


# ---------------------------------------------------------------------------
# 5. 渐变对中文按显示宽度推进
# ---------------------------------------------------------------------------


def test_gradient_advances_by_display_width_for_cjk() -> None:
    """中文每字占 2 列，颜色就该跨 2 列 —— 否则中文段落上渐变会加速漂移。"""
    seq = _rgb_sequence(A.gradient_text("中文abc", col_offset=0, scale=A.BANNER_WIDTH, bold=False))
    ascii_seq = _rgb_sequence(A.gradient_text("......", col_offset=0, scale=A.BANNER_WIDTH, bold=False))
    # "中" 在列 0、"文" 在列 2、"a" 在列 4 ⇒ 与纯 ASCII 串的第 0/2/4 个颜色相同
    assert seq[0] == ascii_seq[0]
    assert seq[1] == ascii_seq[2]
    assert seq[2] == ascii_seq[4]
