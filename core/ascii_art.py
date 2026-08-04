"""
Galaxy ASCII 艺术字 / 统一终端输出格式
=======================================

单一真相来源 (single source of truth) for:
- Galaxy 启动横幅 (GALAXY_BANNER)
- 终端颜色 (Colors) 与 24-bit 渐变 (gradient_text / gradient_rule)
- **版面几何** (BANNER_WIDTH / CONTENT_INDENT / RULE_WIDTH / LABEL_COL / VALUE_COL)
- 显示宽度与填充 (display_width / pad_display) —— 东亚字符算 2 格
- 对齐的状态行 (print_status_row)
- 章节标题 (print_section_header)
- 横幅打印 (print_banner)
- ANSI 支持检测 (ansi_supported)

所有启动入口均应导入并使用本模块的公共接口，以保证视觉一致性。

版面统一（为什么这些常量在这里）
--------------------------------
此前同一屏里存在**三种宽度**（横幅 60 / 章节线 60 / ``cli_render.rule`` 50）、
**三种线条着色**（横幅 24-bit 渐变 / 章节线平 CYAN / 细线平 DIM）、以及
**两套填充语义**（``print_status_row`` 用 ``str.ljust``、``cli_render`` 用显示宽度）。

最后那条是实打实的错位：``ljust`` 按**码点**补齐，中文标签因此偏宽。实测
``"环境检查".ljust(22)`` 的显示宽度是 **26**、``"三态覆盖层"`` 是 **27**，而
``pad_display(..., 22)`` 恒为 22 —— 两套打印器在同一屏里各自缩进，差 2~5 列。

现在几何只有一份，且**渐变是屏幕列的函数**（见 :func:`gradient_text`）：
一条缩进 2 格的横线，其颜色是横幅在第 2..59 列的那一段，因此横线与横幅
不只是"同款配色"，而是**同一道渐变的延续**，左右边缘都对齐。
"""

import os
import re
import sys
import unicodedata

#: 剥 ANSI 转义序列用（算显示宽度前必须剥掉，否则颜色码会被算进列数）。
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# ---------------------------------------------------------------------------
# 版本 & 标语 (single source of truth)
# ---------------------------------------------------------------------------

GALAXY_VERSION = "v2.3.21"
GALAXY_TAGLINE = "L4 Autonomous Intelligence System"

# ---------------------------------------------------------------------------
# 版面几何 (canonical layout geometry) —— 全仓唯一一份
# ---------------------------------------------------------------------------
#
# 一切对齐以横幅为基准。横幅占屏幕第 0..59 列（实测 12 行全部宽 60，且每个
# 字符都是 1 显示格：框线字符 ═║╔╗╚╝ 与 █ 的 east_asian_width 均为 'A'）。

#: 横幅显示宽度。所有横线、章节线的右边缘都对齐到这一列。
BANNER_WIDTH = 60

#: 内容左缩进（格）。``print_status_row`` 与 ``cli_render.phase`` 都用它。
CONTENT_INDENT = 2

#: 横线宽度 = 横幅宽度 − 缩进，使横线右边缘与横幅右边框同列。
#: 此前 ``cli_render.RULE_WIDTH`` 是 50，比横幅短 10 列、右边缘悬空。
RULE_WIDTH = BANNER_WIDTH - CONTENT_INDENT

#: 图标列宽（格）：1 格图标 + 1 格间隔。图标统一为 1 显示格的文本符号
#: （不用 ✅/⚠️ 这类带变体选择符、多数终端渲染成 2 格的 emoji）。
ICON_COL = 2

#: 标签列宽（格）。中英混排在此列内按**显示宽度**左对齐。
LABEL_COL = 22

#: 值列起始屏幕列 = 缩进 + 图标 + 标签 + 2 格间隔。
#: 所有打印器的值都从这一列起，跨模块严格同列。
VALUE_COL = CONTENT_INDENT + ICON_COL + LABEL_COL + 2

# ---------------------------------------------------------------------------
# 规范横幅 (canonical banner)
# 宽度 60 字符 (含边框)，与 shell 脚本中的 echo 版本精确对齐
# Version line is composed from GALAXY_TAGLINE / GALAXY_VERSION constants.
# ---------------------------------------------------------------------------

_BANNER_VERSION_LINE = ("║     " + GALAXY_TAGLINE + "   " + GALAXY_VERSION).ljust(59) + "║"


def _normalize_banner(lines: list) -> str:
    """Pad each banner line to a uniform width so the right border aligns.

    Lines enclosed by ║...║ that are shorter than the widest line have their
    inner content right-padded with spaces so the closing ║ lands in the same
    column on every row.  Top/bottom border lines (╔...╗ / ╚...╝) are already
    at full width and are left unchanged.

    Args:
        lines: Raw banner lines as a list of strings.

    Returns:
        A single string with ``\\n``-joined, uniformly-width lines.
    """
    width = max(len(line) for line in lines)
    result = []
    for line in lines:
        if len(line) < width and line.startswith("║") and line.endswith("║"):
            inner = line[1:-1].ljust(width - 2)
            result.append("║" + inner + "║")
        else:
            result.append(line)
    return "\n".join(result)


_RAW_BANNER_LINES = [
    "╔══════════════════════════════════════════════════════════╗",
    "║                                                          ║",
    "║   ██████╗  █████╗ ██╗      █████╗ ██╗  ██╗██╗   ██╗    ║",
    "║  ██╔════╝ ██╔══██╗██║     ██╔══██╗╚██╗██╔╝╚██╗ ██╔╝    ║",
    "║  ██║  ███╗███████║██║     ███████║ ╚███╔╝  ╚████╔╝      ║",
    "║  ██║   ██║██╔══██║██║     ██╔══██║ ██╔██╗   ╚██╔╝       ║",
    "║  ╚██████╔╝██║  ██║███████╗██║  ██║██╔╝ ██╗   ██║        ║",
    "║   ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝        ║",
    "║                                                          ║",
    _BANNER_VERSION_LINE,
    "║                                                          ║",
    "╚══════════════════════════════════════════════════════════╝",
]

GALAXY_BANNER = _normalize_banner(_RAW_BANNER_LINES)

# ---------------------------------------------------------------------------
# 向后兼容别名 (backward-compat aliases)
# ---------------------------------------------------------------------------

GALAXY_ASCII = """\
   ██████╗  █████╗ ██╗      █████╗ ██╗  ██╗██╗   ██╗
  ██╔════╝ ██╔══██╗██║     ██╔══██╗╚██╗██╔╝╚██╗ ██╔╝
  ██║  ███╗███████║██║     ███████║ ╚███╔╝  ╚████╔╝
  ██║   ██║██╔══██║██║     ██╔══██║ ██╔██╗   ╚██╔╝
  ╚██████╔╝██║  ██║███████╗██║  ██║██╔╝ ██╗   ██║
   ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝

  {tagline}
  Version: {version}""".format(tagline=GALAXY_TAGLINE, version=GALAXY_VERSION)

GALAXY_ASCII_LARGE = GALAXY_BANNER

# GALAXY_ASCII_MINIMAL now points to the canonical banner for backward compat
GALAXY_ASCII_MINIMAL = GALAXY_BANNER

# ---------------------------------------------------------------------------
# 终端颜色 (terminal colors)
# Windows cmd/PowerShell also supports these since Windows 10 1511+
# ---------------------------------------------------------------------------


class Colors:
    """ANSI 终端颜色代码 (gracefully degrades on unsupported terminals)."""

    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    PURPLE = "\033[35m"
    PINK = "\033[95m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"


def ansi_supported() -> bool:
    """检测当前终端是否支持 ANSI 转义序列。

    - 非 TTY 输出（重定向、CI 无色管道等）→ False
    - Windows：尝试启用 VT 处理（Win 10 1511+），失败则 False
    - Unix/Mac：TTY 即认为支持

    Returns:
        bool: True 表示可安全使用 ANSI 颜色，False 表示应降级为纯文本。
    """
    # NO_COLOR 约定（https://no-color.org/）：只要该变量【存在】(哪怕是空串)
    # 就必须禁用颜色。此前 core/cli_render.py 的模块 docstring 声称"非 TTY /
    # NO_COLOR 时自动纯文本"，但实现里从来没查过它 —— 一个说谎的注释。
    if "NO_COLOR" in os.environ:
        return False
    # GALAXY_NO_COLOR：本项目自己的开关，便于在不影响其它工具的前提下关色。
    if os.environ.get("GALAXY_NO_COLOR", "").strip().lower() in ("1", "true", "yes", "on"):
        return False
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    if os.name == "nt":
        try:
            import ctypes

            if not hasattr(ctypes, "windll"):
                return False
            kernel32 = ctypes.windll.kernel32
            STD_OUTPUT_HANDLE = -11
            ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
            mode = ctypes.c_ulong(0)
            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                return False
            if mode.value & ENABLE_VIRTUAL_TERMINAL_PROCESSING:
                return True
            if kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING):
                return True
            return False
        except Exception:
            return False
    return True


# ---------------------------------------------------------------------------
# 24-bit true-color gradient anchors (left → right)
# Scheme: aurora cyan → tech blue → indigo → neon purple → cyber pink
# ---------------------------------------------------------------------------

_ANCHOR_COLORS = [
    (0, 225, 253),  # aurora cyan
    (41, 156, 255),  # tech blue
    (109, 92, 255),  # indigo
    (184, 61, 245),  # neon purple
    (255, 46, 147),  # cyber pink
]


def display_width(s: str) -> int:
    """字符串的**终端显示宽度**：先剥 ANSI，东亚宽/全角字符算 2 格，其余 1 格。

    这个函数原本住在 ``core/cli_render.py``，而 ``print_status_row`` 在本模块里
    却用 ``str.ljust`` —— 两套填充语义并存，中文标签因此错位 2~5 列。下移到
    本模块（较低层）后 ``cli_render`` 再导出去，全仓只剩这一份实现。
    """
    s = _ANSI_RE.sub("", s)
    w = 0
    for ch in s:
        if unicodedata.combining(ch):
            continue
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def pad_display(s: str, width: int, align: str = "left") -> str:
    """按**显示宽度**补空格到 ``width``（不截断；已超宽则原样返回）。"""
    pad = max(0, width - display_width(s))
    return (s + " " * pad) if align == "left" else (" " * pad + s)


def _interp_rgb(t: float) -> tuple:
    """Interpolate RGB across _ANCHOR_COLORS for t in [0.0, 1.0].

    Args:
        t: Position along the gradient, 0.0 = leftmost anchor, 1.0 = rightmost.

    Returns:
        Tuple (r, g, b) with values in 0–255.
    """
    anchors = _ANCHOR_COLORS
    n = len(anchors) - 1  # 4 segments
    scaled = t * n
    i = int(scaled)
    if i >= n:
        return anchors[-1]
    frac = scaled - i
    r1, g1, b1 = anchors[i]
    r2, g2, b2 = anchors[i + 1]
    return (
        int(r1 + (r2 - r1) * frac),
        int(g1 + (g2 - g1) * frac),
        int(b1 + (b2 - b1) * frac),
    )


def gradient_text(text: str, *, col_offset: int = 0, scale: int = BANNER_WIDTH, bold: bool = True) -> str:
    """把 24-bit 渐变按**屏幕列**铺到 ``text`` 上。

    这是本模块的渐变核心。关键点在于 **t 是屏幕列的函数，不是字符序号的函数**：

        t = (col_offset + 该字符左边缘所在列) / (scale - 1)

    因此一条缩进 2 格、宽 58 的横线（``col_offset=2, scale=60``）拿到的颜色，
    正是横幅在第 2..59 列的那一段 —— 它与横幅**不只是同款配色，而是同一道
    渐变的延续**，左右边缘都对齐。若按字符序号算（旧实现），同一条横线会把
    整条渐变压缩进 58 格，与横幅的第 2..59 列对不上。

    列的推进用**显示宽度**而非码点数：中文标题里每个汉字占 2 列，颜色才不会
    在中文段落上加速漂移。横幅本身全是 1 格字符（实测 12 行 code_points ==
    display_width == 60），所以对横幅而言新旧实现**逐字节一致**。

    Args:
        text:       要着色的文本。
        col_offset: 这段文本左边缘所在的屏幕列。
        scale:      渐变全程覆盖的总列数（默认 :data:`BANNER_WIDTH`）。
        bold:       是否前置一次加粗（横幅用 True，保持既有观感）。

    Returns:
        每字符带 ``\\x1b[38;2;R;G;Bm`` 的字符串，末尾复位。
    """
    if not text:
        return text
    span = scale if scale > 1 else 2
    parts = ["\x1b[1m"] if bold else []
    col = col_offset
    for char in text:
        t = col / (span - 1)
        if t < 0.0:
            t = 0.0
        elif t > 1.0:
            t = 1.0
        r, g, b = _interp_rgb(t)
        parts.append(f"\x1b[38;2;{r};{g};{b}m{char}")
        col += 0 if unicodedata.combining(char) else display_width(char)
    parts.append("\x1b[0m")
    return "".join(parts)


def gradient_rule(
    width: int = RULE_WIDTH,
    *,
    indent: int = CONTENT_INDENT,
    char: str = "─",
) -> str:
    """生成一条**与横幅同一道渐变**的横线（含左缩进）。

    此前全仓有三种线条处理：横幅是 24-bit 渐变、``print_section_header`` 是平
    CYAN 的 ``═``×60、``cli_render.rule`` 是平 DIM 的 ``─``×50。现在统一成这一个
    出口 —— 颜色同源、右边缘同列。

    终端不支持 ANSI 时自动降级为纯字符（缩进与宽度不变，纯文本下依然对齐）。
    """
    body = char * width
    if not ansi_supported():
        return " " * indent + body
    return " " * indent + gradient_text(body, col_offset=indent, scale=max(indent + width, 2), bold=False)


def _colorize_line(line: str, banner_width: int = 60) -> str:
    """横幅整行着色（向后兼容入口，内部走 :func:`gradient_text`）。

    保留这个名字是因为 ``print_banner`` 与 ``windows_service/tray_icon.py`` 都在用。
    行为与改造前一致：横幅每个字符都是 1 显示格，故按列推进 == 按码点推进。
    """
    return gradient_text(line, col_offset=0, scale=banner_width, bold=True)


# ---------------------------------------------------------------------------
# 状态图标映射 (trailing spaces removed — print_status_row adds uniform spacing)
# ---------------------------------------------------------------------------

# 与 core.cli_render 统一为【一套 1 显示格的文本符号】(不再混用 ✅/⚠️/❌ 这类带变体
# 选择符、多数终端渲染成 2 格的 emoji)——否则同一屏里 emoji 行(2 格)、▶ 行(1 格)、
# cli_render 的 ✓ 行(1 格)三种图标宽度不一,对勾列各自缩进,永远对不齐。统一成 1 格
# 文本符号后,配合下面 print_status_row 的"图标+单空格"排版,标签一律从第 4 列起,
# 与 cli_render 的 phase()/detail() 完全同列。
_STATUS_ICONS: dict = {
    "success": "✓",
    "warning": "⚠",
    "error": "✗",
    "loading": "◐",
    "step": "▶",
    "info": "·",
}


def get_status_icon(status: str) -> str:
    """返回给定状态对应的图标字符串。"""
    return _STATUS_ICONS.get(status, _STATUS_ICONS["info"])


# ---------------------------------------------------------------------------
# 公共打印助手 (public print helpers)
# ---------------------------------------------------------------------------


def print_powershell_hint() -> None:
    """Print a one-time startup tip for Windows PowerShell users.

    Recommends Consolas font, ≥120-column window width, and UTF-8 code page so
    that the Galaxy ASCII banner renders without broken borders or missing glyphs.

    The hint is only printed when the process is running inside a Windows
    PowerShell session (detected via the ``PSModulePath`` or ``PSVersionTable``
    environment variables) and is silently skipped on other platforms.
    """
    if os.name != "nt" or not (os.environ.get("PSModulePath") or os.environ.get("PSVersionTable")):
        return
    print(
        "\n[Galaxy Tip] PowerShell 显示建议:\n"
        "  • 字体:   Consolas (右键标题栏 → 属性 → 字体)\n"
        "  • 列宽:   窗口宽度 ≥ 120 列 (属性 → 布局 → 宽度 120)\n"
        "  • UTF-8:  运行 chcp 65001 后再启动 Galaxy\n"
        "  示例: chcp 65001 && python main.py\n"
    )


def print_banner(use_color: bool = True) -> None:
    """打印规范 Galaxy 横幅（24-bit true-color 平滑左→右渐变）。

    ANSI 支持自动检测：
    - 若终端支持 ANSI（包括 Windows 10+ VT 模式），每个字符使用独立的
      24-bit RGB 颜色 (``\\x1b[38;2;R;G;Bm``)，从极光青平滑渐变至赛博粉，
      无色彩断层。
    - 若终端不支持（如未启用 VT 的 PowerShell、重定向输出），降级为纯文本。

    Args:
        use_color: 若为 False，强制使用纯文本（不尝试 ANSI 检测）。
    """
    _use_ansi = use_color and ansi_supported()
    if _use_ansi:
        lines = GALAXY_BANNER.split("\n")
        print()
        for line in lines:
            print(_colorize_line(line))
        print()
    else:
        print(f"\n{GALAXY_BANNER}\n")


def print_section_header(title: str, use_color: bool = True) -> None:
    """打印章节分隔标题，宽度 60 字符。

    Example output::

        ════════════════════════════════════════════════════════════
          ▶  服务启动
        ════════════════════════════════════════════════════════════

    Args:
        title:     章节名称。
        use_color: 若为 True（默认），使用青色加粗样式。
    """
    sep = "═" * BANNER_WIDTH
    colored = use_color and ansi_supported()
    if colored:
        line = gradient_text(sep, col_offset=0, scale=BANNER_WIDTH, bold=False)
        c = f"{Colors.BOLD}{Colors.CYAN}"
        e = Colors.ENDC
    else:
        line = sep
        c = e = ""
    print(f"\n{line}")
    print(f"{c}{' ' * CONTENT_INDENT}▶  {title}{e}")
    print(f"{line}\n")


def print_status_row(
    label: str,
    value: str = "",
    status: str = "info",
    label_width: int = LABEL_COL,
    use_color: bool = True,
) -> None:
    """打印对齐的状态行（图标 + 左对齐标签 + 右侧值）。

    Example output::

        ✅  Python                       3.11.0
        ⚠️   Tailscale                    未运行
        ❌  API Key                      未配置

    Args:
        label:       左侧标签文字。
        value:       右侧值文字（可选）。
        status:      状态类型，决定图标和颜色
                     ("success" | "warning" | "error" | "loading" | "step" | "info")。
        label_width: 标签列宽（字符数），默认 28。
        use_color:   是否应用 ANSI 颜色。
    """
    icon = get_status_icon(status)

    color_map = {
        "success": Colors.GREEN,
        "warning": Colors.YELLOW,
        "error": Colors.RED,
        "loading": Colors.CYAN,
        "step": Colors.CYAN,
        "info": Colors.BLUE,
    }

    # 必须同时满足"调用方要色"与"终端支持色"。此前只看 use_color(默认 True),
    # 于是重定向输出、CI、以及 NO_COLOR 环境下这里照样吐 ANSI 转义码,而同屏的
    # cli_render 已经降级成纯文本 —— 一半带色一半不带,管道里还会混进乱码。
    if use_color and ansi_supported():
        color = color_map.get(status, Colors.BLUE)
        end = Colors.ENDC
    else:
        color = end = ""

    # 图标 + 【单】空格(图标现为 1 显示格),标签左对齐 —— 标签从第 4 列起,与
    # core.cli_render 的 phase()/detail() 同列,对勾/标签跨两套打印器完全对齐。
    # 这里必须用 pad_display 而不是 str.ljust:ljust 按【码点】补齐,中文标签
    # 会偏宽。实测 "环境检查".ljust(22) 的显示宽度是 26、"三态覆盖层" 是 27,
    # 而 cli_render 那边恒为 22 —— 同一屏里两套打印器差 2~5 列,对勾对不齐。
    padded = pad_display(label, label_width)
    if value:
        print(f"{' ' * CONTENT_INDENT}{color}{icon} {padded}{end}  {value}")
    else:
        print(f"{' ' * CONTENT_INDENT}{color}{icon} {padded}{end}")


# ---------------------------------------------------------------------------
# 旧版兼容函数 (legacy compat)
# ---------------------------------------------------------------------------


def print_galaxy(style: str = "minimal") -> None:
    """打印 Galaxy ASCII 艺术字（旧版接口，新代码请使用 print_banner()）。"""
    if style == "large":
        print(GALAXY_ASCII_LARGE)
    elif style == "minimal":
        print(GALAXY_ASCII_MINIMAL)
    else:
        print(GALAXY_ASCII)


if __name__ == "__main__":
    print_banner()
    print_section_header("系统状态")
    print_status_row("Python", "3.11.0", "success")
    print_status_row("依赖", "已就绪", "success")
    print_status_row("Tailscale", "未运行", "warning")
    print_status_row("API Key", "未配置", "error")
