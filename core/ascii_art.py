"""
Galaxy ASCII 艺术字 / 统一终端输出格式
=======================================

单一真相来源 (single source of truth) for:
- Galaxy 启动横幅 (GALAXY_BANNER)
- 终端颜色 (Colors)
- 对齐的状态行 (print_status_row)
- 章节标题 (print_section_header)
- 横幅打印 (print_banner)
- ANSI 支持检测 (ansi_supported)

所有启动入口均应导入并使用本模块的公共接口，以保证视觉一致性。
"""

import sys
import os

# ---------------------------------------------------------------------------
# 版本 & 标语 (single source of truth)
# ---------------------------------------------------------------------------

GALAXY_VERSION = "v2.3.21"
GALAXY_TAGLINE = "L4 Autonomous Intelligence System"

# ---------------------------------------------------------------------------
# 规范横幅 (canonical banner)
# 宽度 60 字符 (含边框)，与 shell 脚本中的 echo 版本精确对齐
# Version line is composed from GALAXY_TAGLINE / GALAXY_VERSION constants.
# ---------------------------------------------------------------------------

_BANNER_VERSION_LINE = (
    "║     " + GALAXY_TAGLINE + "   " + GALAXY_VERSION
).ljust(59) + "║"


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
    HEADER = '\033[95m'
    BLUE   = '\033[94m'
    CYAN   = '\033[96m'
    GREEN  = '\033[92m'
    YELLOW = '\033[93m'
    RED    = '\033[91m'
    PURPLE = '\033[35m'
    PINK   = '\033[95m'
    ENDC   = '\033[0m'
    BOLD   = '\033[1m'
    DIM    = '\033[2m'


def ansi_supported() -> bool:
    """检测当前终端是否支持 ANSI 转义序列。

    - 非 TTY 输出（重定向、CI 无色管道等）→ False
    - Windows：尝试启用 VT 处理（Win 10 1511+），失败则 False
    - Unix/Mac：TTY 即认为支持

    Returns:
        bool: True 表示可安全使用 ANSI 颜色，False 表示应降级为纯文本。
    """
    if not hasattr(sys.stdout, 'isatty') or not sys.stdout.isatty():
        return False
    if os.name == 'nt':
        try:
            import ctypes
            if not hasattr(ctypes, 'windll'):
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
    (  0, 225, 253),  # aurora cyan
    ( 41, 156, 255),  # tech blue
    (109,  92, 255),  # indigo
    (184,  61, 245),  # neon purple
    (255,  46, 147),  # cyber pink
]


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


def _colorize_line(line: str, banner_width: int = 60) -> str:
    """Apply 24-bit true-color smooth gradient across every character of *line*.

    Each column gets its own RGB value computed by interpolating across the
    five anchor colors, producing a seamless left-to-right gradient with zero
    banding.

    Args:
        line:         The text to colorize.
        banner_width: Total width used for the color calculation (default 60,
                      matching GALAXY_BANNER). All lines of the banner share
                      this same scale, so colors align consistently across
                      lines of varying code-point length.

    Returns:
        String with per-character ``\\x1b[1;38;2;R;G;Bm`` escape codes,
        terminated by a reset sequence.
    """
    if not line:
        return line
    # Use a fixed scale so every banner line maps columns to the same colors,
    # regardless of per-line code-point count differences.
    width = banner_width if banner_width > 1 else 2
    parts = ["\x1b[1m"]  # bold once at start
    for col, char in enumerate(line):
        t = col / (width - 1)
        r, g, b = _interp_rgb(t)
        parts.append(f"\x1b[38;2;{r};{g};{b}m{char}")
    parts.append("\x1b[0m")
    return "".join(parts)


# ---------------------------------------------------------------------------
# 状态图标映射 (trailing spaces removed — print_status_row adds uniform spacing)
# ---------------------------------------------------------------------------

_STATUS_ICONS: dict = {
    "success": "✅",
    "warning": "⚠️",
    "error":   "❌",
    "loading": "⏳",
    "step":    "▶",
    "info":    "ℹ️",
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
    if os.name != 'nt' or not (os.environ.get("PSModulePath") or os.environ.get("PSVersionTable")):
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
    sep = "═" * 60
    if use_color:
        c = f"{Colors.BOLD}{Colors.CYAN}"
        e = Colors.ENDC
    else:
        c = e = ""
    print(f"\n{c}{sep}{e}")
    print(f"{c}  ▶  {title}{e}")
    print(f"{c}{sep}{e}\n")


def print_status_row(
    label: str,
    value: str = "",
    status: str = "info",
    label_width: int = 28,
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
        "error":   Colors.RED,
        "loading": Colors.CYAN,
        "step":    Colors.CYAN,
        "info":    Colors.BLUE,
    }

    if use_color:
        color = color_map.get(status, Colors.BLUE)
        end   = Colors.ENDC
    else:
        color = end = ""

    padded = label.ljust(label_width)
    if value:
        print(f"  {color}{icon}  {padded}{value}{end}")
    else:
        print(f"  {color}{icon}  {padded}{end}")


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
