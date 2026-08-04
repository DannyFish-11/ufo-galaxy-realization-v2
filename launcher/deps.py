"""launcher/deps.py — 依赖引导的共享层（镜像轮换、探测、分层清单）

四份依赖引导，四个不同的答案
----------------------------
"这个项目需要装什么、怎么装"目前有四份实现，而且它们**互相矛盾**：

=================  ==============================  ==============================
                   装什么                          怎么抗弱网
=================  ==============================  ==============================
``main.py`` Ph.2   **探测**一份精选模块清单，       pip **三候选**轮换
                   只装缺的                        （默认源 → 清华 → 阿里云）
``install.py``     ``requirements-core/-enhance/   **零镜像**（国内几乎必失败）
                   -windows.txt`` 三档全量装
``install.sh``     ``requirements.txt`` 全量装      **一个**镜像（清华，可用
                                                    ``GALAXY_PIP_INDEX`` 覆盖）
``install_win``    ``requirements-core/-enhance/    **零镜像**
``.ps1``           -windows.txt``
``launch_desktop`` ``requirements.txt`` 全量装      **零镜像**、零重试
Phase 1
=================  ==============================  ==============================

其中 ``install.py`` / ``install.sh`` / ``install_windows.ps1`` **全都没有调用方**
—— README 与 INSTALL.md 直接教用户 ``pip install -r requirements.txt``。按
"零引用 ≠ 死重"的判据，它们是**没接线的能力**，不因此删除；但它们各自缺的镜像
轮换是真缺陷，一旦有人真去跑，在国内基本必失败。

为什么不把两类合成一个函数
--------------------------
表面看这是"四份重复"，实际是**两类不同的工作**，合成一个函数会两头都做坏：

* **启动期自愈**（``main.py`` Phase 2 / ``launch_desktop`` Phase 1）：每次开机都
  跑，必须**快**，且位于网关 bind **之前** —— 在这里做全量 ``pip install -r
  requirements.txt`` 会让首启多等好几分钟，网关一直不监听。所以它**探测**：
  import 得动就跳过，只装真缺的那几个。
* **安装期引导**（``install*.``）：从 clone 起跑一次，可以慢、可以阻塞、该装全
  就装全，还要建 venv、预下载模型、建桌面快捷方式。

``main.py`` Phase 2 的注释里明确写着**不在启动时现装语音依赖**（pip 慢、
faster-whisper 几百 MB、卡住就把首启拖死），而 ``install.sh`` 恰恰阻塞式地装它们。
这**不是**矛盾 —— 它正是两层该分开的证据：安装期阻塞没问题，启动期不行。

所以这里合并的是两层**真正共用**的东西：镜像轮换 + 重试 + 诚实上报 + "这个项目
需要什么"的**单一清单**。两层各自的时序策略保留在各自的调用方。

刻意的边界
----------
与 :mod:`launcher.env_check` 同：**本模块不打印**，只做事并返回
:class:`InstallResult`。打印一律经 ``launcher/ui.py``。
"""

from __future__ import annotations

import dataclasses
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── pip 镜像候选（此前 main.py 有三个、install.sh 有一个、另两个一个都没有）──
#
# 顺序刻意是"默认源优先"：尊重用户已配置的 ``pip.conf`` / 企业内网源，失败了才
# 轮换国内镜像。反过来（镜像优先）会让境外用户平白绕道。
_DEFAULT_PIP_INDEXES: Tuple[Optional[str], ...] = (
    None,  # 默认源
    "https://pypi.tuna.tsinghua.edu.cn/simple",
    "https://mirrors.aliyun.com/pypi/simple/",
)


def pip_index_candidates() -> List[Optional[str]]:
    """pip 源候选列表。

    ``GALAXY_PIP_INDEX`` 沿用 ``install.sh`` 已有的约定（那是四份里唯一提供了
    覆盖开关的一份）：设成具体 URL 则只用它；设成 ``default`` 则只用官方源。
    """
    override = (os.environ.get("GALAXY_PIP_INDEX") or "").strip()
    if override.lower() == "default":
        return [None]
    if override:
        return [override]
    return list(_DEFAULT_PIP_INDEXES)


#: electron 二进制镜像候选（取自 ``main.py`` Phase 2 —— 四份里唯一有这层的）。
#: 每项是 (ELECTRON_MIRROR 值, 额外 npm 参数)。空串 = 回退官方源。
ELECTRON_MIRROR_ATTEMPTS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("https://npmmirror.com/mirrors/electron/", ()),
    ("https://registry.npmmirror.com/-/binary/electron/", ("--registry=https://registry.npmmirror.com",)),
    ("", ()),
)

#: npm 网络重试参数（取自 ``main.py``）。
NPM_NET_FLAGS: Tuple[str, ...] = (
    "--fetch-retries=5",
    "--fetch-retry-mintimeout=10000",
    "--fetch-retry-maxtimeout=120000",
    "--fetch-timeout=300000",
)


# ── "这个项目需要什么"的单一答案 ────────────────────────────────────────

#: 启动期**必须**在位的模块：``import 名 -> pip 名``。
#:
#: 这份清单此前只存在于 ``main.py`` 函数体里，三个 installer 谁也不知道它。
#: 它比 ``requirements.txt`` 短得多是刻意的 —— 启动期只保证"跑得起来"，
#: 其余交给安装期分层。
CORE_MODULES: Dict[str, str] = {
    "fastapi": "fastapi",
    "pydantic": "pydantic",
    "httpx": "httpx",
    "uvicorn": "uvicorn",
    "starlette": "starlette",
    "ollama": "ollama",
    "nats": "nats-py",
    "websockets": "websockets",
    "jsonschema": "jsonschema",  # 事件总线 schema 校验
    "huggingface_hub": "huggingface-hub",  # 本地模型 HF 下载 + Ollama 回退
    "tqdm": "tqdm",  # 模型下载进度条
    "edge_tts": "edge-tts",  # TTS 默认引擎；缺了就是"回复出字、一句话不说"
    "opentelemetry.sdk": "opentelemetry-sdk",  # otel 默认开，得真装上才不是纸面开关
}

#: 语音依赖：**故意不在启动期自动装**（见模块头）。清单本身仍要有单一定义，
#: 因为安装期要装它、启动期要**探测并如实报告**它。
VOICE_MODULES: Dict[str, str] = {
    "sounddevice": "sounddevice",
    "pvporcupine": "pvporcupine",
    "webrtcvad": "webrtcvad",
    "faster_whisper": "faster-whisper",
}


def platform_core_modules() -> Dict[str, str]:
    """核心清单 + 按平台追加的高性能事件循环。

    Windows 默认 Proactor 循环开销大（真机：面板首开并发把循环拖出 10s 级冻结），
    winloop ≈5×；Linux/macOS 用 uvloop。装不上都自动退回默认循环，零风险。
    """
    mods = dict(CORE_MODULES)
    mods["winloop" if os.name == "nt" else "uvloop"] = "winloop" if os.name == "nt" else "uvloop"
    return mods


#: 安装期的三档分层。取自 ``install.py`` / ``install_windows.ps1`` —— 那是四份
#: 里唯一做了分层的（``install.sh`` 与 ``launch_desktop`` 都是一把梭
#: ``requirements.txt``）。
REQUIREMENT_TIERS: Dict[str, str] = {
    "core": "requirements-core.txt",
    "enhance": "requirements-enhance.txt",
    "windows": "requirements-windows.txt",
}


@dataclasses.dataclass(frozen=True)
class InstallResult:
    """一次安装尝试的结果。**诚实上报**：失败就是失败，不吞。"""

    ok: bool
    target: str
    """装的是什么（包名列表或 requirements 文件名）。"""

    index_used: Optional[str] = None
    """真正成功的那个源（``None`` = 默认源）。失败时是最后一个尝试过的。"""

    attempts: int = 0
    stderr_tail: str = ""
    """失败时的末尾输出（截断）。成功时为空。"""

    skipped_reason: str = ""
    """非空表示这次压根没跑（如 requirements 文件不存在）—— 与"跑了且成功"
    必须能区分开，否则"跳过"会被当成"装好了"。"""


def probe_missing(modules: Dict[str, str]) -> List[str]:
    """返回 ``modules`` 里 **import 不动**的那些包的 pip 名。

    用**真 import**（``__import__``），不用 ``importlib.util.find_spec``
    ————————————————————————————————————————————————————————————
    ``find_spec`` 只查"找不找得到模块文件"，不执行模块顶层代码，看起来更轻更快。
    这里**不能**用它，因为本仓库有一个反例是写进 ``main.py`` 注释里的既定判断：

        ``sounddevice`` 的顶层 import 会**一并加载 PortAudio 原生库**，所以
        import 失败也能兜住"PortAudio 缺失"。

    换成 ``find_spec``，一台"装了 sounddevice 但系统没有 PortAudio"的机器会被
    判成"语音依赖齐全"，横幅打 ✓，而麦克风采集根本打不开 —— 正是那条注释记录
    的、已经修过一次的误导。

    换句话说：**能不能 import 起来**才是这里要问的问题，"文件在不在"不是。
    代价是模块顶层代码会真的执行一次，这是明知的取舍，不是疏忽。
    """
    missing: List[str] = []
    for mod_name, pip_name in modules.items():
        try:
            __import__(mod_name)
        except Exception:  # noqa: BLE001 — 任何原因导致 import 不起来都算缺
            missing.append(pip_name)
    return missing


def pip_install(
    packages: Sequence[str],
    *,
    timeout: int = 900,
    upgrade: bool = False,
    stream: bool = True,
) -> InstallResult:
    """逐个源候选安装，全部失败才返回失败。

    三条弱网加固（取自 ``main.py``，四份里最强的一份）：

    1. **流式输出**（``stream=True`` 时不 capture）：进度可见，避免"看着像卡死"；
    2. **逐镜像回退**：默认源失败后轮换国内镜像，抗单点；
    3. pip 自带 ``--retries 3 --timeout 60``。

    ``stream=False`` 时捕获输出，失败时把末尾放进 ``stderr_tail`` —— 安装期
    脚本要用它给出可操作的报错。
    """
    pkgs = list(packages)
    if not pkgs:
        return InstallResult(ok=True, target="", skipped_reason="没有要装的包")

    base = [sys.executable, "-m", "pip", "install", "--retries", "3", "--timeout", "60"]
    if upgrade:
        base.append("--upgrade")
    base += pkgs

    candidates = pip_index_candidates()
    last_err = ""
    for idx, index_url in enumerate(candidates):
        cmd = list(base)
        if index_url:
            host = index_url.split("//", 1)[-1].split("/", 1)[0]
            cmd += ["-i", index_url, "--trusted-host", host]
        try:
            if stream:
                rc = subprocess.run(cmd, timeout=timeout).returncode
                err = ""
            else:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout
                )
                rc, err = proc.returncode, (proc.stderr or "")[-400:]
        except subprocess.TimeoutExpired:
            rc, err = 1, f"超时（{timeout}s）"
        except Exception as exc:  # noqa: BLE001
            rc, err = 1, f"{type(exc).__name__}: {exc}"
        if rc == 0:
            return InstallResult(ok=True, target=", ".join(pkgs), index_used=index_url, attempts=idx + 1)
        last_err = err
    return InstallResult(
        ok=False,
        target=", ".join(pkgs),
        index_used=candidates[-1] if candidates else None,
        attempts=len(candidates),
        stderr_tail=last_err,
    )


def install_requirements(tier: str, *, root: Optional[Path] = None, timeout: int = 1800) -> InstallResult:
    """按档安装 requirements 文件。

    文件不存在时返回 ``ok=True`` 且 ``skipped_reason`` 非空 —— 沿用
    ``install.py`` 的"不阻塞"语义，但**把"跳过"与"装好了"分开表示**。
    原实现两者都返回 ``True``，于是一个打错名字的档位会被报成安装成功。
    """
    if tier not in REQUIREMENT_TIERS:
        return InstallResult(ok=False, target=tier, skipped_reason="", stderr_tail=f"未知档位：{tier}")
    rel = REQUIREMENT_TIERS[tier]
    path = (root or PROJECT_ROOT) / rel
    if not path.exists():
        return InstallResult(ok=True, target=rel, skipped_reason=f"{rel} 不存在")
    return pip_install(["-r", str(path)], timeout=timeout, stream=True)


def npm_install(
    cwd: Path,
    *,
    npm_path: Optional[str] = None,
    timeout: int = 900,
) -> InstallResult:
    """``npm install`` + electron 二进制镜像轮换。

    两条真机来的硬要求：

    * **用绝对路径调用 npm**。Windows 上 npm 是 ``npm.cmd``，``CreateProcess``
      不套用 ``PATHEXT`` —— 传裸 ``"npm"`` 会 ``FileNotFoundError``，报成"依赖
      安装失败"，而 npm 其实好端端装着。
    * **不 capture**：npm 进度条要可见，否则慢网下看着像卡死。
    """
    import shutil as _shutil

    npm = npm_path or _shutil.which("npm")
    if not npm:
        return InstallResult(ok=False, target="npm install", stderr_tail="npm 未安装或不在 PATH")

    last_err = ""
    for idx, (mirror, extra) in enumerate(ELECTRON_MIRROR_ATTEMPTS):
        env = dict(os.environ)
        if mirror:
            env["ELECTRON_MIRROR"] = mirror
        try:
            rc = subprocess.run(
                [npm, "install", *NPM_NET_FLAGS, *extra], cwd=str(cwd), env=env, timeout=timeout
            ).returncode
        except Exception as exc:  # noqa: BLE001
            rc, last_err = 1, f"{type(exc).__name__}: {exc}"
        if rc == 0:
            return InstallResult(ok=True, target="npm install", index_used=mirror or None, attempts=idx + 1)
    return InstallResult(
        ok=False,
        target="npm install",
        attempts=len(ELECTRON_MIRROR_ATTEMPTS),
        stderr_tail=last_err or "所有 electron 镜像候选均失败",
    )


__all__ = [
    "CORE_MODULES",
    "VOICE_MODULES",
    "REQUIREMENT_TIERS",
    "ELECTRON_MIRROR_ATTEMPTS",
    "NPM_NET_FLAGS",
    "InstallResult",
    "pip_index_candidates",
    "platform_core_modules",
    "probe_missing",
    "pip_install",
    "install_requirements",
    "npm_install",
]
