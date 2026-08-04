"""launcher/shell.py — 桌面壳的健康诊断与自愈阶梯

它解决什么
----------
桌面壳的自愈逻辑此前是 ``unified_launcher.start_electron()`` 里的一段 160 行内联
流程。那段代码本身是**对的** —— 每一级都是真机故障攒出来的 —— 但它有两个结构上
的问题，而这两个问题正是"自愈看起来没生效"的来源：

1. **不启动就诊断不了**。想知道"我这台机器的桌面壳到底缺什么"，唯一办法是真的
   跑一次启动，然后读日志倒推。装好了没有、包完不完整、二进制在不在、有没有
   残留暂存目录、锁是不是陈旧的 —— 这些都是**可以静态查出来**的事实，却必须
   先拉起一个进程才看得到。
2. **哪一级救活的、哪一级没跑，事后说不清**。七级自愈嵌在一串 ``if`` 里，日志
   是散落的 ``logger.warning``。修好了不知道是哪一步修的；没修好也不知道卡在
   第几级。

本模块把同一套判据重排成两件事：

* :func:`diagnose` —— **纯查，零副作用**，产出 :class:`ShellHealth`；
* :func:`self_heal` —— 按**显式的阶梯**逐级施救，每一级都记下"是否适用 / 是否
  执行 / 结果如何"，产出 :class:`HealReport`。

判据一条没改
------------
七级的**内容**是从 ``unified_launcher`` 原样搬来的，包括每一条注释里记录的真机
症状。改的只是组织方式：从"嵌在一个 async 方法里的 if 链"变成"可单独查询的事实
 + 可逐级审计的阶梯"。

七级自愈阶梯（顺序有意义，不能重排）
------------------------------------
=====  ==========================  ================================================
级别   触发条件                    为什么必须有这一级（真机症状）
=====  ==========================  ================================================
0      ``.electron.pid`` 锁有效    另一条启动路径已经拉起了桌面壳。此前 4 条启动
                                   路径里只有 1 条写这把锁，其余 3 条互不知情 →
                                   重复起壳。
1      ``node_modules`` 不存在     首次克隆，正常安装。
2      包不完整                    ``.bin/electron.cmd`` 存根在、``electron/cli.js``
                                   缺失（npm install 中断的残局）。旧判断"目录在
                                   →跳过"会让 Electron 每次以 "Cannot find module
                                   …cli.js" 崩掉，保活重启 8 次全是同一个死法，
                                   期间**从未尝试过真正的修复**。
3      npm 残留暂存目录            不清就撞 ``ENOTEMPTY``：暂存名已存在且非空 →
                                   "检测到不完整→重装→ENOTEMPTY→仍不完整"死循环，
                                   桌面覆盖层永远起不来。
4      官方源网络失败              ETIMEDOUT / ECONNRESET / TLS…（国内网络常见）
                                   → 换 npmmirror 重试，而不是直接放弃桌面壳。
5      仍被残留目录挡住            换镜像绕不过本地文件系统。唯一确定能解开的办法
                                   是整个删掉 ``node_modules`` 重建 —— 它完全可由
                                   ``package.json`` 重建，删除无损。
6      装完仍不完整                electron 包目录已存在时 npm install 会**跳过
                                   postinstall**，不会补下 ``dist/electron.exe``
                                   运行时二进制 —— 光重跑 install 永远修不好，必须
                                   单独跑包自带的 ``install.js``。
=====  ==========================  ================================================

渲染降级是另一条正交的阶梯（不属于"安装自愈"）
----------------------------------------------
硬件加速 → 软件渲染（``GALAXY_ELECTRON_GPU=0``）→ 不透明 basic 小窗
（``GALAXY_ELECTRON_BASIC=1``）。第三级保留功能、只丢透明特效，而不是彻底放弃
桌面壳。见 :func:`render_env`。

刻意的边界
----------
与 :mod:`launcher.env_check` / :mod:`launcher.deps` 同：本模块**不打印**。
所有基元（锁、完整性、暂存目录、二进制修复）都委托
``core.electron_launch_guard`` —— 那是它们的家，这里不复制一份。
"""

from __future__ import annotations

import dataclasses
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ELECTRON_DIR = PROJECT_ROOT / "electron"

#: 判定"这次 npm 失败是网络问题"的关键词。原样取自 ``unified_launcher``。
NETWORK_FAILURE_MARKERS: Sequence[str] = (
    "ETIMEDOUT",
    "ECONNRESET",
    "ECONNREFUSED",
    "EAI_AGAIN",
    "network",
    "socket",
    "TLS",
    "fetch failed",
)

#: npm 换源重试用的镜像。与 :mod:`launcher.deps` 的 electron 二进制镜像不是一回事
#: —— 那个是 ``ELECTRON_MIRROR``（下二进制），这个是 registry（下包）。
NPM_MIRROR_REGISTRY = "https://registry.npmmirror.com"

NPM_INSTALL_TIMEOUT = 600


@dataclasses.dataclass(frozen=True)
class ShellHealth:
    """桌面壳的**事实**。``diagnose()`` 产出，零副作用。"""

    electron_dir_exists: bool
    npm_path: Optional[str]
    node_modules_exists: bool
    package_intact: bool
    local_binary: Optional[str]
    """本地 electron 可执行文件（``node_modules/.bin/electron[.cmd]``）的绝对路径。"""

    staging_dirs: int
    """npm 中断留下的暂存目录数（``.<包名>-<随机后缀>``）。>0 就会撞 ENOTEMPTY。"""

    lock_held: bool
    """``.electron.pid`` 指向一个**活着的**进程 —— 说明别的启动路径已经起过了。"""

    tauri_binary: Optional[str]

    @property
    def ready(self) -> bool:
        """不用装任何东西就能直接拉起 Electron。"""
        return (
            self.electron_dir_exists and self.npm_path is not None and self.node_modules_exists and self.package_intact
        )

    @property
    def needs_install(self) -> bool:
        return self.electron_dir_exists and (not self.node_modules_exists or not self.package_intact)

    @property
    def blocked(self) -> Optional[str]:
        """自愈也救不了的硬阻塞，返回原因；能救则 ``None``。"""
        if not self.electron_dir_exists:
            return "electron/ 目录不存在"
        if self.npm_path is None:
            return "npm 不在 PATH（自愈装不了依赖）"
        return None

    def to_dict(self) -> Dict[str, Any]:
        d = dataclasses.asdict(self)
        d["ready"] = self.ready
        d["needs_install"] = self.needs_install
        d["blocked"] = self.blocked
        return d


@dataclasses.dataclass
class HealStep:
    """自愈阶梯上的一级。"""

    level: int
    name: str
    applied: bool = False
    """这一级**是否被执行**（不适用时为 False）。"""

    ok: Optional[bool] = None
    """执行结果。``None`` = 没执行。"""

    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class HealReport:
    """一次自愈的完整过程记录。

    存在的意义就是回答那两个此前答不上来的问题：**哪一级救活的**、
    **没救活的话卡在第几级**。
    """

    before: ShellHealth
    after: Optional[ShellHealth] = None
    steps: List[HealStep] = dataclasses.field(default_factory=list)
    ok: bool = False

    @property
    def healed_at(self) -> Optional[int]:
        """真正把问题解决掉的那一级；本来就好的返回 ``None``。"""
        applied = [s for s in self.steps if s.applied and s.ok]
        return applied[-1].level if applied and self.ok else None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "healed_at": self.healed_at,
            "before": self.before.to_dict(),
            "after": self.after.to_dict() if self.after else None,
            "steps": [s.to_dict() for s in self.steps],
        }


# ── 诊断：纯查 ────────────────────────────────────────────────────────


def diagnose(electron_dir: Optional[Path] = None) -> ShellHealth:
    """查出桌面壳的全部事实。**不装、不删、不起进程。**

    这是本模块存在的主要理由：此前这些事实只能通过"真的跑一次启动然后读日志"
    间接得到。
    """
    root = electron_dir if electron_dir is not None else ELECTRON_DIR
    exists = root.is_dir()
    npm = shutil.which("npm")
    node_modules = root / "node_modules"
    nm_exists = node_modules.is_dir()

    intact = False
    if exists and nm_exists:
        try:
            from core.electron_launch_guard import electron_package_intact

            intact = bool(electron_package_intact(str(root)))
        except Exception:
            intact = False

    bin_name = "electron.cmd" if os.name == "nt" else "electron"
    local_bin = node_modules / ".bin" / bin_name
    staging = _count_staging_dirs(node_modules) if nm_exists else 0

    lock = False
    try:
        from core.electron_launch_guard import already_running

        lock = bool(already_running())
    except Exception:
        lock = False

    return ShellHealth(
        electron_dir_exists=exists,
        npm_path=npm,
        node_modules_exists=nm_exists,
        package_intact=intact,
        local_binary=str(local_bin) if local_bin.exists() else None,
        staging_dirs=staging,
        lock_held=lock,
        tauri_binary=find_tauri_binary(),
    )


def _count_staging_dirs(node_modules: Path) -> int:
    """数 npm 残留暂存目录，**不删**。

    删除是 :func:`self_heal` 第 3 级的事；诊断阶段只能看，不能改 —— 否则
    "诊断"就有了副作用，跑一次诊断就把现场破坏了。
    """
    from core.electron_launch_guard import _NPM_KEEP_DOTTED, _NPM_STAGING_RE

    try:
        return sum(
            1
            for entry in node_modules.iterdir()
            if entry.is_dir() and entry.name not in _NPM_KEEP_DOTTED and _NPM_STAGING_RE.match(entry.name)
        )
    except OSError:
        return 0


def find_tauri_binary() -> Optional[str]:
    """找 Tauri 壳的可执行文件。

    双壳选择的判据**就是"这个二进制在不在"** —— 取自 ``unified_launcher``：
    只查一个文件，不做任何能力探测。刻意保持这么简单，因为它在启动关键路径上。
    """
    candidates = [
        PROJECT_ROOT / "tauri-shell" / "src-tauri" / "target" / "release" / "galaxy-shell",
        PROJECT_ROOT / "tauri-shell" / "src-tauri" / "target" / "release" / "galaxy-shell.exe",
        PROJECT_ROOT / "tauri-shell" / "src-tauri" / "target" / "debug" / "galaxy-shell",
        PROJECT_ROOT / "tauri-shell" / "src-tauri" / "target" / "debug" / "galaxy-shell.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


# ── 自愈：显式阶梯 ────────────────────────────────────────────────────


def _npm_install(npm: str, cwd: Path, *, registry: Optional[str] = None) -> subprocess.CompletedProcess:
    cmd = [npm, "install"]
    if registry:
        cmd.append(f"--registry={registry}")
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=NPM_INSTALL_TIMEOUT,
    )


def _looks_like_network_failure(output: str) -> bool:
    return any(marker in output for marker in NETWORK_FAILURE_MARKERS)


def self_heal(health: Optional[ShellHealth] = None, *, electron_dir: Optional[Path] = None) -> HealReport:
    """按七级阶梯逐级施救，全过程可审计。

    每一级都会在 :class:`HealReport` 里留一条 :class:`HealStep`，标明**是否适用**、
    **是否执行**、**结果如何** —— 这样"修好了是哪一步修的""没修好卡在第几级"
    事后答得上来。原来这两个问题只能靠翻散落的 ``logger.warning`` 猜。
    """
    root = electron_dir if electron_dir is not None else ELECTRON_DIR
    before = health if health is not None else diagnose(root)
    report = HealReport(before=before)

    def step(level: int, name: str) -> HealStep:
        s = HealStep(level=level, name=name)
        report.steps.append(s)
        return s

    # ── 0 级：别的启动路径已经起过了 ──
    s0 = step(0, "复用已在运行的桌面壳（.electron.pid 锁）")
    s0.detail = "锁未持有，需要自己拉起"
    if before.lock_held:
        s0.applied, s0.ok, s0.detail = True, True, "锁有效，无需重复拉起"
        report.after, report.ok = before, True
        return report

    blocked = before.blocked
    if blocked:
        s0.detail = f"硬阻塞：{blocked}"
        report.after, report.ok = before, False
        return report

    if not before.needs_install:
        s0.detail = "依赖已完整，无需自愈"
        report.after, report.ok = before, True
        return report

    npm = before.npm_path
    assert npm is not None  # blocked 已排除
    node_modules = root / "node_modules"

    # ── 3 级前置：清残留暂存目录（必须在任何 install 之前） ──
    # 顺序不能改：不清就撞 ENOTEMPTY，而"不完整→重装→ENOTEMPTY→仍不完整"是死循环。
    s3 = step(3, "清理 npm 残留暂存目录（防 ENOTEMPTY 死循环）")
    if before.staging_dirs:
        try:
            from core.electron_launch_guard import purge_npm_staging_dirs

            purged = purge_npm_staging_dirs(str(node_modules))
            s3.applied, s3.ok, s3.detail = True, True, f"清掉 {purged} 个"
        except Exception as exc:  # noqa: BLE001
            s3.applied, s3.ok, s3.detail = True, False, f"{type(exc).__name__}: {exc}"
    else:
        s3.detail = "没有残留目录"

    # ── 1/2 级：正常安装（缺失是 1，残缺是 2；同一个动作，原因不同） ──
    level = 1 if not before.node_modules_exists else 2
    s1 = step(level, "首次安装 Electron 依赖" if level == 1 else "修复安装（依赖不完整）")
    try:
        proc = _npm_install(npm, root)
        s1.applied = True
        s1.ok = proc.returncode == 0
        s1.detail = "" if s1.ok else (proc.stderr or proc.stdout or "")[-300:]
    except Exception as exc:  # noqa: BLE001
        s1.applied, s1.ok, s1.detail = True, False, f"{type(exc).__name__}: {exc}"
        proc = None

    # ── 4 级：网络失败换镜像 ──
    s4 = step(4, f"改用国内镜像重试（{NPM_MIRROR_REGISTRY}）")
    if proc is not None and proc.returncode != 0:
        output = proc.stderr or proc.stdout or ""
        if _looks_like_network_failure(output):
            try:
                proc = _npm_install(npm, root, registry=NPM_MIRROR_REGISTRY)
                s4.applied = True
                s4.ok = proc.returncode == 0
                s4.detail = "" if s4.ok else (proc.stderr or proc.stdout or "")[-300:]
            except Exception as exc:  # noqa: BLE001
                s4.applied, s4.ok, s4.detail = True, False, f"{type(exc).__name__}: {exc}"
        else:
            s4.detail = "失败不像网络问题，不换源"
    else:
        s4.detail = "上一级已成功"

    # ── 5 级：仍被残留目录挡住 → 整体重建 ──
    s5 = step(5, "整体重建 node_modules（换镜像绕不过本地文件系统）")
    if proc is not None and proc.returncode != 0:
        try:
            from core.electron_launch_guard import is_npm_stale_dir_error

            if is_npm_stale_dir_error(proc.stderr or proc.stdout or ""):
                # node_modules 完全可由 package.json 重建，删除无损。
                shutil.rmtree(str(node_modules), ignore_errors=True)
                proc = _npm_install(npm, root)
                s5.applied = True
                s5.ok = proc.returncode == 0
                s5.detail = "" if s5.ok else (proc.stderr or proc.stdout or "")[-300:]
            else:
                s5.detail = "不是残留目录问题"
        except Exception as exc:  # noqa: BLE001
            s5.applied, s5.ok, s5.detail = True, False, f"{type(exc).__name__}: {exc}"
    else:
        s5.detail = "无需重建"

    if proc is not None and proc.returncode != 0:
        # 装不上就到不了第 6 级。但**仍然要把它记下来**并写明"没到" ——
        # 否则报告里那一级凭空消失，读的人分不清"跑了没用"和"根本没跑到"。
        step(6, "补下 electron 运行时二进制（npm 跳过了 postinstall）").detail = "前面的安装未成功，未到这一级"
        report.after = diagnose(root)
        report.ok = False
        return report

    # ── 6 级：装完仍不完整 → 单独补运行时二进制 ──
    # electron 包目录已存在时 npm install 会跳过 postinstall，不补 dist/electron.exe，
    # 光重跑 install 永远修不好。
    s6 = step(6, "补下 electron 运行时二进制（npm 跳过了 postinstall）")
    mid = diagnose(root)
    if not mid.package_intact:
        try:
            from core.electron_launch_guard import repair_electron_binary

            fixed = bool(repair_electron_binary(str(root.resolve())))
            s6.applied, s6.ok = True, fixed
            if not fixed:
                from core.electron_launch_guard import electron_binary_fix_hint

                s6.detail = electron_binary_fix_hint("electron")
        except Exception as exc:  # noqa: BLE001
            s6.applied, s6.ok, s6.detail = True, False, f"{type(exc).__name__}: {exc}"
    else:
        s6.detail = "包已完整"

    report.after = diagnose(root)
    report.ok = report.after.ready
    return report


# ── 渲染降级：与安装自愈正交的另一条阶梯 ──────────────────────────────


def render_env(*, force_software: bool = False, basic_window: bool = False) -> Dict[str, str]:
    """按降级档位产出要注入 Electron 的环境变量。

    三档（原样取自 ``unified_launcher``）：

    1. 默认走**硬件加速** —— 有独显的机器更流畅；
    2. ``force_software`` → ``GALAXY_ELECTRON_GPU=0``，``main.js`` 据此禁用硬件
       加速 + ``--disable-gpu`` + ``--disable-gpu-compositing``（真正的纯软件渲染）；
    3. ``basic_window`` → 再加 ``GALAXY_ELECTRON_BASIC=1``，改用**不透明 basic
       小窗**承载三态覆盖层 —— 功能保留、只丢透明特效，而不是彻底放弃桌面壳。
       这一档是给"无独显 Windows 上透明分层窗口本身出问题"准备的。
    """
    env: Dict[str, str] = {}
    if force_software or basic_window:
        env["GALAXY_ELECTRON_GPU"] = "0"
    if basic_window:
        env["GALAXY_ELECTRON_BASIC"] = "1"
    return env


def preferred_shell(health: Optional[ShellHealth] = None) -> str:
    """选哪个壳：``"tauri"`` | ``"electron"`` | ``"none"``。

    Tauri 优先（系统 WebView，不背 Chromium，常驻内存/启动/体积都远小于
    Electron），判据就是"二进制在不在"。``GALAXY_DESKTOP_SHELL=electron``
    强制回退 —— 这个开关原样保留。
    """
    h = health if health is not None else diagnose()
    if (os.environ.get("GALAXY_DESKTOP_SHELL") or "").strip().lower() == "electron":
        return "electron" if (h.ready or h.electron_dir_exists) else "none"
    if h.tauri_binary:
        return "tauri"
    if h.electron_dir_exists:
        return "electron"
    return "none"


__all__ = [
    "ELECTRON_DIR",
    "NETWORK_FAILURE_MARKERS",
    "NPM_MIRROR_REGISTRY",
    "ShellHealth",
    "HealStep",
    "HealReport",
    "diagnose",
    "self_heal",
    "render_env",
    "preferred_shell",
    "find_tauri_binary",
]
