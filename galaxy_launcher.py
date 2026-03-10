#!/usr/bin/env python3
"""
Galaxy 智能启动器 — 已废弃，请使用 unified_launcher.py
==================================================

[DEPRECATED] 此文件已废弃。所有功能已合并到 unified_launcher.py。
保留此文件仅为向后兼容，所有调用将转发到 unified_launcher。

推荐用法:
    python unified_launcher.py  → 唯一推荐入口
    python main.py              → 标准入口（委托到 unified_launcher）
"""

import sys
import warnings
import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.absolute()

warnings.warn(
    "galaxy_launcher.py 已废弃，请直接使用 unified_launcher.py",
    DeprecationWarning,
    stacklevel=2,
)


def main() -> int:
    """转发到 unified_launcher.py"""
    print(
        "[DEPRECATED] galaxy_launcher.py 已废弃，正在转发到 unified_launcher.py ...",
        file=sys.stderr,
    )
    launcher = _PROJECT_ROOT / "unified_launcher.py"
    if not launcher.exists():
        print(f"错误: unified_launcher.py 未找到: {launcher}", file=sys.stderr)
        return 1
    args = [sys.executable, str(launcher)] + sys.argv[1:]
    return subprocess.call(args)


if __name__ == "__main__":
    sys.exit(main())
