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
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ContainerRuntime")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CHOICE_FILE = PROJECT_ROOT / ".galaxy_runtime"

_RUNTIMES = ("docker", "podman")
# 交互菜单里【推荐】的运行时:Podman 无守护、rootless、更轻,Windows 上一条 winget
# 就能装(Docker Desktop 太重、还要单独装/开守护)。仅影响用户实际看到的选择菜单的
# 默认项与排序;非交互/headless 路径仍保持 docker 优先(见 available_runtimes)。
_RECOMMENDED = "podman"
_LABELS: Dict[str, str] = {
    "docker": "Docker —— 最广泛;需 Docker Desktop / Engine + 守护进程(较重)",
    "podman": "Podman —— 无守护、rootless、更轻,一条 winget 即可装(推荐)",
}


def _prefer_recommended(runtimes: List[str]) -> List[str]:
    """把推荐运行时(Podman)排到最前,其余保持原相对顺序。用于交互菜单的展示与默认项。"""
    rec = [rt for rt in runtimes if rt == _RECOMMENDED]
    rest = [rt for rt in runtimes if rt != _RECOMMENDED]
    return rec + rest


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
            raw = _CHOICE_FILE.read_text(encoding="utf-8").strip()
            if not raw:
                return ""
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    rt = str(data.get("runtime", "")).strip().lower()
                    return rt if rt in _RUNTIMES else ""
            except json.JSONDecodeError:
                pass
            rt = raw.lower()
            return rt if rt in _RUNTIMES else ""
    except Exception:  # noqa: BLE001
        pass
    return ""


def load_choice_record() -> Dict[str, Any]:
    """读取持久化的运行时选择记录（兼容旧版纯文本）。"""
    try:
        if not _CHOICE_FILE.exists():
            return {}
        raw = _CHOICE_FILE.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"runtime": raw.lower(), "source": "legacy", "selected_at": None}
        if not isinstance(data, dict):
            return {}
        rt = str(data.get("runtime", "")).strip().lower()
        if rt not in _RUNTIMES:
            return {}
        return {
            "runtime": rt,
            "source": str(data.get("source", "unknown") or "unknown"),
            "selected_at": data.get("selected_at"),
        }
    except Exception:  # noqa: BLE001
        return {}


def save_choice(rt: str, source: str = "unknown") -> None:
    """持久化选择并写 GALAXY_CONTAINER_RUNTIME,让后续启动无需再问。"""
    if rt not in _RUNTIMES:
        return
    try:
        payload = {
            "runtime": rt,
            "source": source,
            "selected_at": datetime.now(timezone.utc).isoformat(),
        }
        _CHOICE_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
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

    # 展示与默认项把推荐运行时(Podman·更轻)排到最前;回车即用它。
    avail = _prefer_recommended(avail)

    from core import cli_render as r
    from core.ascii_art import Colors

    def _c(t, color):
        return f"{color}{t}{Colors.ENDC}" if r._use_color() else t

    print()
    print("  " + _c("选择容器运行时", Colors.BOLD + Colors.CYAN) + _c("  (后台拉取并运行节点基础设施)", Colors.DIM))
    r.rule()
    for i, rt in enumerate(avail, 1):
        is_first = i == 1
        marker = _c("▸", Colors.GREEN) if is_first else " "
        num = _c(f"[{i}]", Colors.BOLD if is_first else Colors.DIM)
        name = r.pad_display(rt.capitalize(), 10)
        tail = _c("  ← 推荐" if rt == _RECOMMENDED else "  ← 默认", Colors.GREEN) if is_first else ""
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


_INSTALL_HINTS: Dict[str, str] = {
    "docker": "https://docs.docker.com/get-docker/ (Windows 装 Docker Desktop)",
    "podman": "https://podman.io/get-started (Windows: winget install RedHat.Podman)",
}

# 各平台【自动安装】命令。Windows 用 winget(会弹 UAC,由用户确认),Podman 最轻;
# Linux 用发行版包管理器(需 sudo,无 sudo 权限时会失败,属尽力而为);macOS 用 brew。
_WINGET_ID: Dict[str, str] = {"docker": "Docker.DockerDesktop", "podman": "RedHat.Podman"}


def can_auto_install() -> bool:
    """当前平台是否具备【后台自动安装】容器运行时的手段(winget / brew / apt / dnf)。"""
    if sys.platform == "win32":
        return shutil.which("winget") is not None
    if sys.platform == "darwin":
        return shutil.which("brew") is not None
    return any(shutil.which(pm) for pm in ("apt-get", "dnf", "pacman", "zypper"))


def _install_command(rt: str) -> Optional[List[str]]:
    """返回在当前平台自动安装 rt 的命令(拿不到返回 None)。"""
    if rt not in _RUNTIMES:
        return None
    if sys.platform == "win32":
        wg = shutil.which("winget")
        if wg and rt in _WINGET_ID:
            return [
                wg,
                "install",
                "--id",
                _WINGET_ID[rt],
                "-e",
                "--silent",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ]
        return None
    if sys.platform == "darwin":
        brew = shutil.which("brew")
        if brew:
            # docker 用 cask(Docker Desktop),podman 是普通 formula
            return [brew, "install", "--cask", "docker"] if rt == "docker" else [brew, "install", "podman"]
        return None
    # Linux:优先 apt,其次 dnf/pacman/zypper。docker 用发行版包名 docker.io / docker;
    # 无 sudo 时会失败(尽力而为)。Podman 在各发行版包名统一为 podman。
    pkg = "podman" if rt == "podman" else ("docker.io" if shutil.which("apt-get") else "docker")
    for pm, args in (
        ("apt-get", ["install", "-y", pkg]),
        ("dnf", ["install", "-y", pkg]),
        ("pacman", ["-S", "--noconfirm", pkg]),
        ("zypper", ["install", "-y", pkg]),
    ):
        if shutil.which(pm):
            base = ["sudo", pm] if shutil.which("sudo") else [pm]
            return base + args
    return None


def background_install(rt: str) -> bool:
    """后台【静默/尽力而为】安装容器运行时(不阻塞启动)。返回是否已发起安装进程。

    Windows 会弹 UAC 由用户确认(无法真正完全静默安装系统级软件,这是 OS 的安全约束);
    其它平台用包管理器(可能需 sudo)。安装日志写 logs/container_runtime_install.log。
    装好后【下次启动】即自动检测并采用(偏好已由调用方持久化)。
    """
    cmd = _install_command(rt)
    if not cmd:
        return False
    import subprocess as _sp
    import threading as _th
    from pathlib import Path as _Path

    def _run() -> None:
        try:
            _log_dir = _Path("logs")
            _log_dir.mkdir(exist_ok=True)
            with open(_log_dir / "container_runtime_install.log", "ab") as _f:
                _f.write(f"\n== auto-install {rt}: {cmd} ==\n".encode("utf-8", "replace"))
                _f.flush()
                _sp.run(cmd, stdout=_f, stderr=_sp.STDOUT, timeout=1800)
        except Exception as exc:  # noqa: BLE001
            logger.info("容器运行时自动安装(%s)未完成(尽力而为): %s", rt, exc)

    _th.Thread(target=_run, name=f"GalaxyRuntimeInstall-{rt}", daemon=True).start()
    return True


def interactive_install_guide() -> str:
    """两者都【未安装】且交互时:仍展示选择菜单,让用户选定偏好运行时并给出安装指引。

    容器运行时的二进制需系统级安装(需管理员/重启,无法静默拉取),故这里不"下载",
    而是【选偏好 + 给安装链接】,并把选择持久化——装好后下次启动即自动采用、后台静默
    拉取节点镜像。非交互终端直接返回 "" 不打扰。返回持久化的偏好名(仍 "" 表示当前不可用)。
    """
    if not (sys.stdin and sys.stdin.isatty()):
        return ""
    from core import cli_render as r
    from core.ascii_art import Colors

    def _c(t, color):
        return f"{color}{t}{Colors.ENDC}" if r._use_color() else t

    # 推荐运行时(Podman·更轻)排最前、作默认;Docker 仍可选。
    _menu = _prefer_recommended(list(_RUNTIMES))
    print()
    print(
        "  "
        + _c("选择容器运行时", Colors.BOLD + Colors.CYAN)
        + _c("  (节点基础设施需要;两者都未检测到,先选一个偏好并安装)", Colors.DIM)
    )
    r.rule()
    for i, rt in enumerate(_menu, 1):
        marker = _c("▸", Colors.GREEN) if i == 1 else " "
        num = _c(f"[{i}]", Colors.BOLD if i == 1 else Colors.DIM)
        name = r.pad_display(rt.capitalize(), 10)
        tail = _c("  ← 推荐" if rt == _RECOMMENDED else "  ← 默认", Colors.GREEN) if i == 1 else ""
        print(f"  {marker} {num} {name}{tail}")
        print(f"         {_c(_LABELS.get(rt, ''), Colors.DIM)}")
        print(f"         {_c('安装: ' + _INSTALL_HINTS.get(rt, ''), Colors.DIM)}")
    r.rule()
    print(
        "  " + _c(f"回车=记住默认({_RECOMMENDED.capitalize()}·更轻) · 数字=记住偏好 · s=跳过(桌面照常运行)", Colors.DIM)
    )
    try:
        choice = input(f"  选择偏好运行时 [1-{len(_menu)} / 回车 / s]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return ""
    if choice == "s":
        return ""
    pick = _menu[0]  # 回车 → 推荐(Podman)
    if choice.isdigit() and 1 <= int(choice) <= len(_menu):
        pick = _menu[int(choice) - 1]
    elif choice in _RUNTIMES:
        pick = choice
    save_choice(pick)  # 记住偏好;装好后下次即自动采用
    print("  " + _c(f"已记住偏好: {pick.capitalize()}", Colors.GREEN))
    # 能自动装就【后台自己下】,不用用户手动。Windows 会弹 UAC 确认(系统级软件
    # 无法完全静默,属 OS 安全约束);装好后下次启动自动采用并后台拉取节点镜像。
    if can_auto_install():
        if background_install(pick):
            print(
                "  "
                + _c(
                    f"  正在【后台自动安装】{pick.capitalize()}…(日志 logs/container_runtime_install.log;"
                    f"Windows 会弹一次 UAC 确认)。装好后重跑即自动启用。",
                    Colors.CYAN,
                )
            )
        else:
            print("  " + _c(f"  安装(手动): {_INSTALL_HINTS.get(pick, '')}", Colors.DIM))
    else:
        print("  " + _c(f"  未检测到可用的自动安装工具,请手动安装: {_INSTALL_HINTS.get(pick, '')}", Colors.DIM))
    return ""  # 当前仍不可用(安装进行中/待装),偏好已持久化


def setup_wizard_select_runtime() -> str:
    """首启配置向导专用:【总是】展示 Docker/Podman 完整选择菜单,不因为已装了其中
    一个就静默跳过。

    真 bug 修复:``resolve_runtime()`` 的"只装了一个 → 直接用、不打扰"是【自动化
    静默启动路径】(``unified_launcher.ensure_docker_infra``,每次 ``python main.py``
    都会走)的正确设计——不该在日常启动时突然弹一个交互菜单。但配置向导
    (``setup_wizard.py``,只在 ``python main.py --setup`` 时跑一次)的意图恰恰
    相反:用户主动来"配置"就是想【看到并做选择】,而不是被代码替他决定。之前
    ``_configure_databases()`` 直接调用 ``resolve_runtime(interactive=True)``,
    继承了它"单一已装就跳过菜单"的短路——绝大多数机器只装了 Docker(比 Podman
    普及得多),于是"Docker/Podman 选择"在向导里实际上【几乎从来不出现】,这正是
    "压根就没有"这个报告的真根因,而不是菜单代码本身有 bug。

    环境变量 ``GALAXY_CONTAINER_RUNTIME`` 仍是最高优先级(操作者显式指定,任何
    场景都该尊重,包括这里)。其余情况一律展示菜单;已安装的选项标注"已安装"
    可直接生效,未安装的选项选中后走安装引导(同 ``interactive_install_guide``
    的自动装/手动装分支)。非交互终端(无 TTY)不弹菜单,委托给
    ``resolve_runtime(interactive=False)`` 的静默逻辑,避免在自动化场景卡住。
    """
    env = _env_choice()
    if env in _RUNTIMES and shutil.which(env):
        save_choice(env)
        return env

    if not (sys.stdin and sys.stdin.isatty()):
        return resolve_runtime(interactive=False)

    from core import cli_render as r
    from core.ascii_art import Colors

    def _c(t, color):
        return f"{color}{t}{Colors.ENDC}" if r._use_color() else t

    installed = set(available_runtimes())
    menu = _prefer_recommended(list(_RUNTIMES))
    print()
    print("  " + _c("选择容器运行时", Colors.BOLD + Colors.CYAN) + _c("  (后台拉取并运行节点基础设施)", Colors.DIM))
    r.rule()
    for i, rt in enumerate(menu, 1):
        is_first = i == 1
        marker = _c("▸", Colors.GREEN) if is_first else " "
        num = _c(f"[{i}]", Colors.BOLD if is_first else Colors.DIM)
        name = r.pad_display(rt.capitalize(), 10)
        status = (
            _c("  ✓ 已安装", Colors.GREEN) if rt in installed else _c("  未安装（选中后自动/引导安装）", Colors.DIM)
        )
        tail = (_c("  ← 推荐" if rt == _RECOMMENDED else "  ← 默认", Colors.GREEN) if is_first else "") + status
        print(f"  {marker} {num} {name}{tail}")
        print(f"         {_c(_LABELS.get(rt, ''), Colors.DIM)}")
    r.rule()
    print("  " + _c("回车=用默认 · 数字=手选 · s=跳过(桌面照常运行)", Colors.DIM))
    try:
        choice = input(f"  请选择运行时 [1-{len(menu)} / 回车 / s]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        choice = ""
    if choice == "s":
        return ""
    pick = menu[0]
    if choice.isdigit() and 1 <= int(choice) <= len(menu):
        pick = menu[int(choice) - 1]
    elif choice in _RUNTIMES:
        pick = choice

    if pick in installed:
        save_choice(pick)
        print("  " + _c(f"已选择: {pick.capitalize()}（已安装，立即生效）", Colors.GREEN))
        return pick

    # 选中的运行时尚未安装:记住偏好,尽力后台自动装(同 interactive_install_guide
    # 的安装分支);装好后下次启动即自动采用,本次仍返回 ""(当前不可用)。
    save_choice(pick)
    print("  " + _c(f"已记住偏好: {pick.capitalize()}（尚未安装）", Colors.GREEN))
    if can_auto_install():
        if background_install(pick):
            print(
                "  "
                + _c(
                    f"  正在【后台自动安装】{pick.capitalize()}…(日志 logs/container_runtime_install.log;"
                    f"Windows 会弹一次 UAC 确认)。装好后重跑即自动启用。",
                    Colors.CYAN,
                )
            )
        else:
            print("  " + _c(f"  安装(手动): {_INSTALL_HINTS.get(pick, '')}", Colors.DIM))
    else:
        print("  " + _c(f"  未检测到可用的自动安装工具,请手动安装: {_INSTALL_HINTS.get(pick, '')}", Colors.DIM))
    return ""


def resolve_runtime(interactive: bool = True) -> str:
    """解析并持久化最终容器运行时。返回运行时名("" = 当前无可用运行时)。

    环境 > 已保存(且已装) > 单一已装 > (两者都装且交互)提示 > 都没装:交互则展示
    选择+安装指引菜单(记住偏好、返回 ""),非交互则返回 ""。
    """
    env = _env_choice()
    if env in _RUNTIMES and shutil.which(env):
        save_choice(env, source="env")
        return env

    saved = load_choice()
    if saved in _RUNTIMES and shutil.which(saved):
        os.environ["GALAXY_CONTAINER_RUNTIME"] = saved
        return saved
    if saved in _RUNTIMES and not shutil.which(saved):
        logger.warning("已保存运行时 %s 当前不可用，尝试回退到其它可用运行时", saved)

    avail = available_runtimes()
    if not avail:
        # 都没装:交互时也【给出选择菜单 + 安装指引】(而不是静默跳过),记住偏好。
        if interactive:
            return interactive_install_guide()
        return ""
    if len(avail) == 1:
        save_choice(avail[0], source="single-installed")
        return avail[0]

    if not interactive:
        # 非交互场景：禁止按数组顺序静默默认。若之前有已保存但当前不可用的选择，回退到推荐
        # 运行时（有明确策略且可记录来源）；否则要求用户先显式选择（通过 setup / GUI）。
        # English: in headless mode, we refuse order-based silent defaulting when both runtimes
        # are available and no explicit saved choice exists.
        if saved in _RUNTIMES and saved not in avail:
            fallback = _RECOMMENDED if _RECOMMENDED in avail else avail[0]
            save_choice(fallback, source="fallback-saved-unavailable")
            logger.warning("已从不可用的 %s 回退到 %s", saved, fallback)
            return fallback
        logger.warning(
            "检测到 Docker 与 Podman 同时可用，但无显式已保存选择；非交互启动拒绝静默默认，请先完成显式选择"
        )
        return ""

    chosen = interactive_select(avail)
    if chosen:
        save_choice(chosen, source="interactive-select")
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
        return (
            subprocess.run(
                [bin_, "info"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            ).returncode
            == 0
        )
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
            if (
                subprocess.run(
                    [bin_, "compose", "version"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=15,
                ).returncode
                == 0
            ):
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


def _run_runtime_cmd(cmd: List[str], timeout: int = 10) -> Dict[str, Any]:
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return {
            "ok": p.returncode == 0,
            "returncode": p.returncode,
            "stdout": (p.stdout or "").strip(),
            "stderr": (p.stderr or "").strip(),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "returncode": -1, "stdout": "", "stderr": "timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "returncode": -2, "stdout": "", "stderr": str(exc)}


def inspect_single_runtime(rt: str) -> Dict[str, Any]:
    path = detect_runtimes().get(rt)
    installed = bool(path)
    version = _run_runtime_cmd([path, "--version"], timeout=8) if installed else None
    info = _run_runtime_cmd([path, "info"], timeout=12) if installed else None
    compose = compose_base(rt) if installed else None
    compose_probe = _run_runtime_cmd(compose + ["version"], timeout=8) if compose else None
    machine = None
    if rt == "podman" and installed:
        machine = _run_runtime_cmd([path, "machine", "list", "--format", "json"], timeout=8)
    return {
        "runtime": rt,
        "installed": installed,
        "path": path,
        "version": (version or {}).get("stdout", ""),
        "daemon_ready": bool((info or {}).get("ok")),
        "daemon_error": None if (info or {}).get("ok") else (info or {}).get("stderr", ""),
        "compose_command": compose or [],
        "compose_ready": bool((compose_probe or {}).get("ok")),
        "compose_error": None if (compose_probe or {}).get("ok") else (compose_probe or {}).get("stderr", ""),
        "podman_machine_status_raw": (machine or {}).get("stdout", ""),
    }


def inspect_runtime_state() -> Dict[str, Any]:
    """Serializable runtime snapshot used by launcher/Electron.

    Includes install/version/daemon/compose readiness for both Docker and Podman,
    plus resolved selection source (env/saved/single-installed/none).
    """
    det = detect_runtimes()
    saved_record = load_choice_record()
    saved = saved_record.get("runtime") if saved_record else ""
    env = _env_choice()
    avail = available_runtimes()
    runtimes: Dict[str, Any] = {}
    for rt in _RUNTIMES:
        path = det.get(rt)
        installed = bool(path)
        # 修复(F821,随 #1520 合入):这里引用的 _run_cmd 从未存在过——真实的
        # 命令探测助手叫 _run_runtime_cmd(见上方定义,inspect_single_runtime 用的
        # 就是它)。名字写错导致 inspect_runtime_state() 只要有任一运行时已安装
        # 就 NameError 崩溃,启动器/Electron 拿不到运行时快照;flake8 F821 也把
        # 整个 lint gate 拦死。
        version = _run_runtime_cmd([path, "--version"], timeout=8) if installed else None
        info = _run_runtime_cmd([path, "info"], timeout=12) if installed else None
        compose = compose_base(rt) if installed else None
        compose_probe = _run_runtime_cmd(compose + ["version"], timeout=8) if compose else None
        machine = None
        if rt == "podman" and installed:
            machine = _run_runtime_cmd([path, "machine", "list", "--format", "json"], timeout=8)
        runtimes[rt] = {
            "runtime": rt,
            "installed": installed,
            "path": path,
            "version": (version or {}).get("stdout", ""),
            "daemon_ready": bool((info or {}).get("ok")),
            "daemon_error": None if (info or {}).get("ok") else (info or {}).get("stderr", ""),
            "compose_command": compose or [],
            "compose_ready": bool((compose_probe or {}).get("ok")),
            "compose_error": None if (compose_probe or {}).get("ok") else (compose_probe or {}).get("stderr", ""),
            "podman_machine_status_raw": (machine or {}).get("stdout", ""),
        }

    selected = ""
    selected_source = "none"
    if env in avail:
        selected = env
        selected_source = "env"
    elif saved in avail:
        selected = saved
        selected_source = "saved"
    elif len(avail) == 1:
        selected = avail[0]
        selected_source = "single-installed"

    return {
        "ok": True,
        "env_choice": env if env in _RUNTIMES else "",
        "saved_choice": saved if saved in _RUNTIMES else "",
        "saved_source": (saved_record or {}).get("source", ""),
        "saved_selected_at": (saved_record or {}).get("selected_at"),
        "available": avail,
        "selected": selected,
        "selected_source": selected_source,
        "requires_explicit_choice": len(avail) > 1 and not selected,
        "runtimes": runtimes,
    }


def set_runtime_choice(rt: str, source: str = "manual") -> Dict[str, Any]:
    rt = (rt or "").strip().lower()
    if rt not in _RUNTIMES:
        return {"ok": False, "error": f"invalid runtime: {rt}"}
    if not shutil.which(rt):
        return {"ok": False, "error": f"{rt} not installed"}
    save_choice(rt, source=source)
    return {"ok": True, "runtime": rt, "state": inspect_runtime_state()}


def test_runtime(rt: str) -> Dict[str, Any]:
    rt = (rt or "").strip().lower()
    if rt not in _RUNTIMES:
        return {"ok": False, "error": f"invalid runtime: {rt}"}
    if not shutil.which(rt):
        return {"ok": False, "error": f"{rt} not installed"}
    state = inspect_single_runtime(rt)
    ok = bool(state.get("daemon_ready")) and bool(state.get("compose_ready"))
    return {"ok": ok, "runtime": rt, "details": state}
