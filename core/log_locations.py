"""哪些日志、在哪、什么时候来看 —— **一处登记**。

为什么要有这一处
----------------
仓库里到处是"详情见 XXX 日志":有的说 ``logs/docker.log``,有的说"服务端日志",
有的只说"详情见日志"。三个问题:

1. **各说各的**。同一件事在启动器里叫一个名字、在节点里叫另一个,
   同一个人换个地方看到的话就对不上。
2. **说了等于没说**。"详情见服务端日志"——服务端日志在哪?一个不看代码的人
   没法从这句话走到那个文件。
3. **没有入口**。就算知道路径,也得自己开文件管理器翻。

所以:日志本身登记在这里,右下角托盘按这张表出一个「日志」菜单(见
``windows_service/tray_icon.py``),而所有"详情见…"的措辞都从
:func:`log_hint` 出 —— 一句话里**既有托盘路径、也有文件路径**,
托盘起不来时那句话照样是真的。

新增一条日志时只改这里:托盘菜单和所有提示语会跟着变。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

#: 提示语里统一的那句"去哪找"。改这一个字符串,全仓的措辞一起变。
TRAY_ROUTE = "托盘 → 日志"

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def logs_root() -> Path:
    """日志根目录。``GALAXY_LOG_DIR`` 可覆盖(打包/便携版会用到)。"""
    override = os.environ.get("GALAXY_LOG_DIR", "").strip()
    return Path(override) if override else PROJECT_ROOT / "logs"


@dataclass(frozen=True)
class LogLocation:
    """一条日志的全部事实。

    Attributes:
        name: 稳定标识,代码里用它引用(``log_hint("docker")``)。
        label: 中文名 —— 托盘菜单和提示语里显示的就是它。
        label_en: 英文名,托盘是双语的。
        relpath: 相对 :func:`logs_root` 的路径。目录以 ``/`` 结尾。
        purpose: **什么时候该来看这里**。不是"这是什么",是"你遇到什么问题时来"
            —— 前者对着屏幕的人用不上。
    """

    name: str
    label: str
    label_en: str
    relpath: str
    purpose: str

    @property
    def is_dir(self) -> bool:
        return self.relpath.endswith("/")

    def path(self) -> Path:
        return logs_root() / self.relpath.rstrip("/")

    def exists(self) -> bool:
        p = self.path()
        return p.is_dir() if self.is_dir else p.is_file()


#: 登记表。顺序 = 托盘菜单里的顺序,按"最常需要看"排。
LOG_LOCATIONS: List[LogLocation] = [
    LogLocation(
        name="backend",
        label="后端",
        label_en="Backend",
        relpath="lumiv.log",
        purpose="对话没反应、接口报错、节点行为不对 —— 先看这个",
    ),
    LogLocation(
        name="electron",
        label="桌面壳",
        label_en="Desktop shell",
        relpath="electron.log",
        purpose="面板打不开、窗口一闪就没、界面白屏",
    ),
    LogLocation(
        name="docker",
        label="容器编排",
        label_en="Compose",
        relpath="docker.log",
        purpose="基础设施那一行是黄的 —— 容器没起来的原因在这",
    ),
    LogLocation(
        name="dockerd",
        label="Docker 守护进程",
        label_en="Docker daemon",
        relpath="dockerd.log",
        purpose="这台机器没有 systemd、由启动器直接拉起 dockerd 时,它的输出在这",
    ),
    LogLocation(
        name="podman",
        label="Podman API",
        label_en="Podman API",
        relpath="podman.log",
        purpose="用 Podman 时:引擎在、compose 却连不上它的 socket —— 拉起 socket 的过程在这",
    ),
    LogLocation(
        name="ollama",
        label="本机模型",
        label_en="Local models",
        relpath="ollama.log",
        purpose="本机模型加载不了、显存不够、拉模型卡住",
    ),
    LogLocation(
        name="container_install",
        label="容器运行时安装",
        label_en="Runtime install",
        relpath="container_runtime_install.log",
        purpose="自动装 Docker / Podman 的过程,装不上时看它",
    ),
    LogLocation(
        name="nodes",
        label="各节点",
        label_en="Nodes",
        relpath="nodes/",
        purpose="某一个节点起不来 —— 每个节点一个文件",
    ),
    LogLocation(
        name="crashes",
        label="崩溃现场",
        label_en="Crashes",
        relpath="crashes/",
        purpose="进程崩了留下的现场",
    ),
]

_BY_NAME: Dict[str, LogLocation] = {entry.name: entry for entry in LOG_LOCATIONS}


def get_log(name: str) -> Optional[LogLocation]:
    """按名字取一条登记;没登记过返回 ``None``(**不编一条出来**)。"""
    return _BY_NAME.get(name)


def existing_logs() -> List[LogLocation]:
    """此刻**真的存在**的那些。

    托盘菜单只列这些 —— 列一个点开是空的条目,比不列更让人困惑:
    人会以为"日志是空的",而实际是这条链路压根没跑过。
    """
    return [entry for entry in LOG_LOCATIONS if entry.exists()]


def log_hint(name: str) -> str:
    """ "详情见…"这句话的**唯一出处**。

    一句话里同时给两条路:托盘菜单(点得到)和文件路径(找得到)。
    只给托盘的话,托盘起不来时这句话就是假的;只给路径的话,
    等于让人自己去翻文件夹 —— 而这正是这次要改掉的。

    没登记过的名字返回一句诚实的兜底,而不是拼一个不存在的路径出来。
    """
    entry = get_log(name)
    if entry is None:
        return f"详情见 {TRAY_ROUTE}"
    return f"详情见 {TRAY_ROUTE} → {entry.label}(logs/{entry.relpath})"


__all__ = [
    "TRAY_ROUTE",
    "LogLocation",
    "LOG_LOCATIONS",
    "logs_root",
    "get_log",
    "existing_logs",
    "log_hint",
]
