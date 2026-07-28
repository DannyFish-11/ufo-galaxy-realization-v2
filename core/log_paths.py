"""统一日志根 + 崩溃日志专区(单一事实来源)。

## 为什么需要这个模块

此前仓库里的日志是**散的**,真机排障时用户要在多个地方翻:

- 两个互不相干的根目录:项目内 ``logs/`` 与 ``~/.galaxy/logs``
  (windows_service/daemon 写后者,launcher/fusion 写前者);
- 若干节点直接用裸文件名 ``logging.FileHandler("node_25_google_search.log")``
  ——落在**进程当前工作目录**,启动方式一变就换地方,等于丢失;
- 托盘右键菜单里有两个日志入口("View Logs" 开 ``~/.galaxy/logs``、
  "三态动画日志" 开项目内 ``logs/electron.log``),指向两个不同位置,
  用户根本不知道该点哪个。

崩溃排障是最需要"一眼定位"的场景,却是最散的。本模块把日志根收敛为**一个**,
并在其下开辟 ``crashes/`` 专区,由 :mod:`core.crash_log_aggregator` 把各处日志里
的崩溃/致命片段汇总到 ``crashes/latest.log``,托盘用**单独一行**直接打开它。

## 目录契约

    <LOG_ROOT>/                     # 默认 <项目根>/logs,可用 GALAXY_LOG_DIR 覆盖
    ├── crashes/                    # 崩溃专区(本次新增)
    │   ├── latest.log              # 聚合视图:各源崩溃片段汇总,托盘单行直达
    │   └── <source>.crash.log      # 按来源归档的崩溃明细
    ├── nodes/                      # 各节点日志(node_XX_*.log 归位于此)
    ├── electron.log                # 三态覆盖层
    ├── launcher.log / lumiv.log    # 启动器 / 主程序
    └── ...

## 兼容性

``GALAXY_LOG_DIR`` 环境变量优先(windows_service 已在用它给子进程传目录),
未设置时用项目根 ``logs/``。历史上写 ``~/.galaxy/logs`` 的路径统一改为调用
:func:`log_root`,使两个根合并为一个;``~/.galaxy/logs`` 若已存在旧文件,
:func:`legacy_log_roots` 供迁移/清理逻辑读取,不静默丢弃用户既有日志。
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "log_root",
    "crash_dir",
    "crash_latest_path",
    "node_log_dir",
    "log_path",
    "legacy_log_roots",
    "ENV_LOG_DIR",
]

#: 环境变量名:显式指定日志根目录(windows_service 给子进程注入的就是它)。
ENV_LOG_DIR = "GALAXY_LOG_DIR"

#: 项目根 = 本文件的上两级(core/log_paths.py -> core -> <项目根>)。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def log_root() -> Path:
    """返回**唯一**的日志根目录,并确保其存在。

    优先级:``GALAXY_LOG_DIR`` 环境变量 > ``<项目根>/logs``。
    """
    raw = os.environ.get(ENV_LOG_DIR, "").strip()
    root = Path(raw) if raw else _PROJECT_ROOT / "logs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def crash_dir() -> Path:
    """崩溃日志专区目录 ``<LOG_ROOT>/crashes``(自动创建)。"""
    d = log_root() / "crashes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def crash_latest_path() -> Path:
    """聚合崩溃视图文件路径 —— 托盘"崩溃日志"单行直接打开的就是它。"""
    return crash_dir() / "latest.log"


def node_log_dir() -> Path:
    """节点日志子目录 ``<LOG_ROOT>/nodes``(自动创建)。

    修掉"节点用裸文件名写到进程 CWD"的老问题:同一节点在不同启动方式下
    日志落点不同,排障时找不到。
    """
    d = log_root() / "nodes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_path(name: str) -> Path:
    """返回日志根下某个日志文件的完整路径(父目录自动创建)。

    :param name: 文件名或相对路径(如 ``"electron.log"`` / ``"nodes/x.log"``)。
    """
    p = log_root() / name
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def legacy_log_roots() -> list[Path]:
    """历史遗留日志根(仅用于迁移/清理时读取,不再写入)。

    ``~/.galaxy/logs`` 是 windows_service / daemon 早期使用的第二个根;统一后
    不再写入,但可能残留用户既有日志——迁移工具据此把旧文件搬到统一根,
    绝不静默删除用户数据。
    """
    roots: list[Path] = []
    legacy = Path.home() / ".galaxy" / "logs"
    if legacy.exists() and legacy.resolve() != log_root().resolve():
        roots.append(legacy)
    return roots
