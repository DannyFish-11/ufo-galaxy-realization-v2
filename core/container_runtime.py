"""
core/container_runtime.py — 容器运行时（Docker / Podman）选择与解析
=====================================================================

节点服务的基础设施(NATS/Redis/Qdrant/Neo4j/Mongo)跑在容器里。此前只支持 Docker;
本模块把运行时抽象成【可选 Docker 或 Podman】,并仿 ``core.model_selection`` 的模式
提供:检测 → (两者都装时)交互选择 → 持久化 → 统一的 CLI 抽象(info/compose/up)。

Podman 与 Docker 的 CLI 基本兼容:``podman info`` / ``podman compose`` (或
``podman-compose``) / ``podman ... up -d`` 对应 docker 同名命令,故一套抽象即可。

解析优先级(``resolve_runtime``):
    环境 GALAXY_CONTAINER_RUNTIME > 已保存(.galaxy_runtime)
    > 只装了一个 → 直接用 > 两个都装且交互 → 提示选 > 都没装 → ""(跳过,不阻断)。

选择结果驱动 ``unified_launcher.ensure_docker_infra`` 后台【静默拉取】基础设施镜像并
拉起服务。全程容错,任何分支都不影响桌面启动。
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("Galaxy.ContainerRuntime")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CHOICE_FILE = PROJECT_ROOT / ".galaxy_runtime"

_RUNTIMES = ("docker", "podman")
_LABELS: Dict[str, str] = {
    "docker": "Docker —— 最广泛;Docker Desktop / Engine + docker compose",
    "podman": "Podman —— 无守护进程、rootless、更轻;podman / podman-compose",
}


def detect_runtimes() -> Dict[str, Optional[str]]:
    """返回 {runtime: 可执行路径 或 None}。"""
    return {rt: shutil.which(rt) for rt in _RUNTIMES}


def available_runtimes() -> List[str]:
    """已安装(命令可用)的运行时名列表,docker 优先。"""
    det = detect_runtimes()
    return [rt for rt in _RUNTIMES if det.get(rt)]


def _env_choice() -> str:
    return os.environ.get("GALAXY_CONTAINER_RUNTIME", "").strip().lower()


def load_choice() -> str:
    try:
        if _CHOICE_FILE.exists():
            return _CHOICE_FILE.read_text(encoding="utf-8").strip().lower()
    except Exception:  # noqa: BLE001
        pass
    return ""


def save_choice(rt: str) -> None:
    """持久化选择并写 GALAXY_CONTAINER_RUNTIME,让后续启动无需再问。"""
    if rt not in _RUNTIMES:
        return
    try:
        _CHOICE_FILE.write_text(rt, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    os.environ["GALAXY_CONTAINER_RUNTIME"] = rt


def interactive_select(avail: List[str]) -> str:
    """两个运行时都装了时,让用户选一个作后台基础设施运行时。

    非交互终端(无 TTY)不阻塞:返回 avail[0](docker 优先),由调用方明确说明"已自动选用"。
    渲染走 core.cli_render(与启动界面同一套:对齐、细线)。
    """
    if not avail:
        return ""
    if not (sys.stdin and sys.stdin.isatty()):
        return avail[0]

    from core import cli_render as r
    from core.ascii_art import Colors

    def _c(t, color):
        return f"{color}{t}{Colors.ENDC}" if r._use_color() else t

    print()
    print("  " + _c("选择容器运行时", Colors.BOLD + Colors.CYAN)
          + _c("  (后台拉取并运行节点基础设施)", Colors.DIM))
    r.rule()
    for i, rt in enumerate(avail, 1):
        is_first = (i == 1)
        marker = _c("▸", Colors.GREEN) if is_first else " "
        num = _c(f"[{i}]", Colors.BOLD if is_first else Colors.DIM)
        name = r.pad_display(rt.capitalize(), 10)
        tail = _c("  ← 默认", Colors.GREEN) if is_first else ""
        print(f"  {marker} {num} {name}{tail}")
        print(f"         {_c(_LABELS.get(rt, ''), Colors.DIM)}")
    r.rule()
    print("  " + _c("回车=用默认 · 数字=手选", Colors.DIM))
    while True:
        try:
            choice = input(f"  请选择运行时 [1-{len(avail)} / 回车]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return avail[0]
        if choice == "":
            return avail[0]
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(avail):
                return avail[idx]
        # 也允许直接输入名字
        if choice in avail:
            return choice
        print("  " + _c("⚠ 无效输入，请重新选择（或直接回车用默认）。", Colors.YELLOW))


def resolve_runtime(interactive: bool = True) -> str:
    """解析并持久化最终容器运行时。返回运行时名("" = 无可用运行时,跳过)。

    环境 > 已保存 > 单一已装 > (两者都装且交互)提示 > 都没装 → ""。
    """
    env = _env_choice()
    if env in _RUNTIMES and shutil.which(env):
        save_choice(env)
        return env

    saved = load_choice()
    if saved in _RUNTIMES and shutil.which(saved):
        os.environ["GALAXY_CONTAINER_RUNTIME"] = saved
        return saved

    avail = available_runtimes()
    if not avail:
        return ""
    if len(avail) == 1:
        save_choice(avail[0])
        return avail[0]

    chosen = interactive_select(avail) if interactive else avail[0]
    if chosen:
        save_choice(chosen)
    return chosen


# ── 统一 CLI 抽象:docker / podman 命令基本同名 ──────────────────────────────

def runtime_binary(rt: str) -> Optional[str]:
    return shutil.which(rt) if rt in _RUNTIMES else None


def daemon_up(rt: str) -> bool:
    """运行时守护/引擎是否就绪(``<rt> info`` 成功)。Podman 无守护但 info 同样可用。"""
    bin_ = runtime_binary(rt)
    if not bin_:
        return False
    try:
        return subprocess.run(
            [bin_, "info"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15,
        ).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def compose_base(rt: str) -> Optional[List[str]]:
    """返回该运行时的 compose 命令前缀:
    - docker → [docker, compose] 或 [docker-compose]
    - podman → [podman, compose] 或 [podman-compose]
    找不到返回 None。
    """
    bin_ = runtime_binary(rt)
    if bin_:
        try:
            if subprocess.run(
                [bin_, "compose", "version"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=15,
            ).returncode == 0:
                return [bin_, "compose"]
        except Exception:  # noqa: BLE001
            pass
    # 独立 compose 二进制回退
    standalone = shutil.which(f"{rt}-compose")
    if standalone:
        return [standalone]
    # podman 常见另一形态:podman-compose 不在,但 docker-compose 可驱动 podman socket——
    # 不做隐式跨用,保持清晰;返回 None 交由调用方降级。
    return None


def display_name(rt: str) -> str:
    return rt.capitalize() if rt in _RUNTIMES else "容器运行时"
