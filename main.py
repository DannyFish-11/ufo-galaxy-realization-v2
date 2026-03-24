#!/usr/bin/env python3
"""
Galaxy-Nexus 星枢 — Bootstrap Launcher (Adapter/Launcher Role)
===============================================================

**Unified-Subject Architecture — Bootstrap Script Only**
---------------------------------------------------------
This file is a **bootstrap launcher** — it is NOT a primary subject entrypoint
and does NOT have subject-core authority.  The subject lifecycle is driven by
:class:`~core.desktop_presence_runtime.DesktopPresenceRuntime` (the outer
shell) wrapping :class:`~core.openclawd.OpenClawd` (the subject core).

This script's sole role: bootstrap the process, then yield to
``unified_launcher.py`` which initialises the runtime shell.

所有启动逻辑统一由 unified_launcher.py 处理。
本文件仅作为入口委托，不包含业务逻辑。

使用方法:
    python main.py              → 启动完整 Galaxy-Nexus 系统
    python main.py --setup      → 运行配置向导
    python main.py --status     → 查看系统状态
    python main.py --help       → 查看所有启动选项

其他入口（均委托到同一启动器）:
    python unified_launcher.py  → 直接调用统一启动器（与 main.py 等效）
    python start_galaxy.py      → 兼容性包装器（已弃用，请使用 main.py）
    python start_l4.py          → 兼容性包装器（已弃用，请使用 main.py）
"""

import os
import sys
import subprocess
import logging
from pathlib import Path

# 设置项目根目录
PROJECT_ROOT = Path(__file__).parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

# 配置基础日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("Galaxy")


def main() -> int:
    """主入口 — 委托到 unified_launcher.py"""

    # --setup: 运行配置向导
    if "--setup" in sys.argv:
        wizard_path = PROJECT_ROOT / "setup_wizard.py"
        if wizard_path.exists():
            return subprocess.call([sys.executable, str(wizard_path)])
        logger.error("配置向导未找到: %s", wizard_path)
        return 1

    # 委托到 unified_launcher
    launcher_path = PROJECT_ROOT / "unified_launcher.py"
    if not launcher_path.exists():
        logger.error(
            "统一启动器未找到: %s\n"
            "请确保 unified_launcher.py 存在于项目根目录。",
            launcher_path,
        )
        return 1

    args = [sys.executable, str(launcher_path)] + sys.argv[1:]
    try:
        return subprocess.call(args)
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在退出...")
        return 0
    except Exception as exc:
        logger.error("启动失败: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
