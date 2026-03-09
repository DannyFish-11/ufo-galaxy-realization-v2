#!/usr/bin/env python3
"""
Galaxy 智能启动器 — 已合并到 unified_launcher.py
==================================================

此文件的所有功能已合并到 unified_launcher.py。
保留此文件仅为向后兼容，所有调用将转发到 unified_launcher。

使用方法:
    python unified_launcher.py  → 推荐入口
    python main.py              → 标准入口（也会委托到 unified_launcher）
"""

import sys
import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.absolute()


def main() -> int:
    """转发到 unified_launcher.py"""
    launcher = _PROJECT_ROOT / "unified_launcher.py"
    if not launcher.exists():
        print(f"错误: unified_launcher.py 未找到: {launcher}", file=sys.stderr)
        return 1
    args = [sys.executable, str(launcher)] + sys.argv[1:]
    return subprocess.call(args)


if __name__ == "__main__":
    sys.exit(main())
