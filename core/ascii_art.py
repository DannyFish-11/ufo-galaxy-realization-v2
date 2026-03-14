"""
Galaxy ASCII 艺术字 / 统一终端输出格式
=======================================

单一真相来源 (single source of truth) for:
- Galaxy 启动横幅 (GALAXY_BANNER)
- 终端颜色 (Colors)
- 对齐的状态行 (print_status_row)
- 章节标题 (print_section_header)
- 横幅打印 (print_banner)

所有启动入口均应导入并使用本模块的公共接口，以保证视觉一致性。
"""

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
    ENDC   = '\033[0m'
    BOLD   = '\033[1m'
    DIM    = '\033[2m'


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
    """打印规范 Galaxy 横幅。

    Args:
        use_color: 若为 True（默认），横幅将以青色加粗显示；
                   传入 False 可在不支持 ANSI 的环境中使用。
    """
    if use_color:
        print(f"\n{Colors.CYAN}{Colors.BOLD}{GALAXY_BANNER}{Colors.ENDC}\n")
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
