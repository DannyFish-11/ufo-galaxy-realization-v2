#!/usr/bin/env python3
"""
Galaxy L4 级自主性智能系统启动脚本

.. deprecated::
    This script is retained for backwards compatibility only.
    The recommended entrypoint is ``main.py`` (or ``unified_launcher.py``),
    which starts the full Galaxy system including L4 modules.

    **PR6 — Frozen entrypoint**: ``start_l4.py`` no longer runs L4 logic
    directly.  It now delegates all work to ``unified_launcher.py`` to prevent
    divergent startup paths.  The ``GalaxyMainLoopL4`` class is still available
    for import (it itself carries a deprecation notice), but it is no longer
    instantiated here.

    Migration::

        # Before:
        python start_l4.py

        # After (full system with L4 enabled):
        python main.py
        # or equivalently:
        python unified_launcher.py
"""

import logging
import sys
import warnings
from pathlib import Path

# 添加路径
sys.path.insert(0, str(Path(__file__).parent))

_dep_logger = logging.getLogger("L4Startup")

# Issue the deprecation warning as early as possible so shell wrappers see it.
warnings.warn(
    "start_l4.py is deprecated and has been frozen (PR6). "
    "All startup logic now runs through unified_launcher.py. "
    "Use 'python main.py' or 'python unified_launcher.py' instead. "
    "start_l4.py will be removed in a future release.",
    DeprecationWarning,
    stacklevel=1,
)


def main():
    """兼容入口 — 转发到 unified_launcher.main()。

    PR6: start_l4.py 不再直接实例化 GalaxyMainLoopL4。
    所有启动逻辑由 unified_launcher.py 统一管理，确保只有一条启动链路。
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    _dep_logger.warning(
        "⚠  DEPRECATED / FROZEN: start_l4.py — delegating to unified_launcher.py. "
        "Use 'python main.py' directly to suppress this warning."
    )

    try:
        from core.ascii_art import print_banner
        print_banner()
    except Exception as _banner_err:
        _dep_logger.debug("print_banner 不可用，跳过横幅显示: %s", _banner_err)

    print()
    print("═" * 60)
    print("  ⚠  start_l4.py is a frozen compatibility wrapper (PR6).")
    print("     Delegating to unified_launcher.py …")
    print("═" * 60)
    print()

    # Delegate to unified_launcher — the single authoritative entrypoint.
    try:
        from unified_launcher import main as unified_main
        unified_main()
    except Exception as exc:
        _dep_logger.error("unified_launcher delegation failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()

