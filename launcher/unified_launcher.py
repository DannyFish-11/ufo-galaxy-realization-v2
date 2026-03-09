"""
Unified Launcher for Galaxy — 已合并到顶层 unified_launcher.py
================================================================

此模块的所有功能已合并到项目根目录的 unified_launcher.py。
保留此文件仅为向后兼容。

使用方法:
    python unified_launcher.py  → 推荐入口（项目根目录）
    python main.py              → 标准入口
"""

import sys
import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    """转发到顶层 unified_launcher.py"""
    launcher = _PROJECT_ROOT / "unified_launcher.py"
    if not launcher.exists():
        print(f"错误: unified_launcher.py 未找到: {launcher}", file=sys.stderr)
        return 1
    args = [sys.executable, str(launcher)] + sys.argv[1:]
    return subprocess.call(args)


if __name__ == "__main__":
    sys.exit(main())
