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

GALAXY_BANNER = "\n".join([
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
])

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
# 渐变颜色映射 (gradient colors: cyan → green → purple → blue → pink)
# Each entry maps to one line of GALAXY_BANNER (12 lines total).
# ---------------------------------------------------------------------------

_BANNER_GRADIENT = [
    '\033[96m',  # line 0 : ╔═══ top border — cyan
    '\033[96m',  # line 1 : ║    empty       — cyan
    '\033[92m',  # line 2 : ║   ██ logo r1   — green
    '\033[92m',  # line 3 : ║  ██  logo r2   — green
    '\033[35m',  # line 4 : ║  ██  logo r3   — purple
    '\033[35m',  # line 5 : ║  ██  logo r4   — purple
    '\033[94m',  # line 6 : ║  ██  logo r5   — blue
    '\033[94m',  # line 7 : ║   ╚  logo r6   — blue
    '\033[95m',  # line 8 : ║    empty       — pink
    '\033[95m',  # line 9 : ║     version    — pink
    '\033[95m',  # line 10: ║    empty       — pink
    '\033[95m',  # line 11: ╚═══ bottom      — pink
]


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

def print_banner(use_color: bool = True) -> None:
    """打印规范 Galaxy 横幅（渐变色：cyan→green→purple→blue→pink）。

    ANSI 支持自动检测：
    - 若终端支持 ANSI（包括 Windows 10+ VT 模式），输出渐变彩色横幅。
    - 若终端不支持（如未启用 VT 的 PowerShell、重定向输出），降级为纯文本。

    Args:
        use_color: 若为 False，强制使用纯文本（不尝试 ANSI 检测）。
    """
    _use_ansi = use_color and ansi_supported()
    if _use_ansi:
        lines = GALAXY_BANNER.split("\n")
        print()
        for i, line in enumerate(lines):
            color = _BANNER_GRADIENT[i] if i < len(_BANNER_GRADIENT) else '\033[96m'
            print(f"{Colors.BOLD}{color}{line}\033[0m")
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
