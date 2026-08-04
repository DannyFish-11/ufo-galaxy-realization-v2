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
import re
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
#: 每项是 (electron 二进制镜像 URL, 额外 npm 参数)。最后一项是**官方源**。
#:
#: 为什么第三项从空串改成了官方源的真实 URL
#: ----------------------------------------
#: 空串原本的含义是"什么都不设，让 npm 用默认值"。真跑之后发现这条路是**空的**：
#: ``electron/.npmrc`` 里钉着 ``electron_mirror=https://npmmirror.com/...``，
#: 不显式覆盖它就永远是那一个值 —— 于是"回退官方源"这一级实际上在**重跑第一级**。
#: 实测 ``npm config get electron_mirror``：设 ``ELECTRON_MIRROR=""`` 之后仍然返回
#: npmmirror。既然要回退，就得给出真实 URL 并用能压过 .npmrc 的方式传。
ELECTRON_MIRROR_ATTEMPTS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("https://npmmirror.com/mirrors/electron/", ()),
    ("https://registry.npmmirror.com/-/binary/electron/", ("--registry=https://registry.npmmirror.com",)),
    ("https://github.com/electron/electron/releases/download/", ()),
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

    healed: str = ""
    """非空表示这次是**自愈之后**才装成功的，值是那一步做了什么
    （如 ``--ignore-installed PyYAML``）。要让用户知道"装上了，但动了点手脚"，
    而不是当成一次平平无奇的成功 —— 下次换台机器可能又会撞上。"""

    stopped_early: bool = False
    """失败不是网络造成的，所以**没有**把剩下的源试完。

    区分这两种失败对用户是有意义的：``attempts == len(candidates)`` 且本项为
    ``False`` 才是"三个源都不通"（该查网络）；本项为 ``True`` 说明换源不可能有用，
    该看 :attr:`stderr_tail` 里的真实原因。"""


#: pip 输出里"这是网络问题"的标志词。
#:
#: 用途和 :data:`launcher.shell.NETWORK_FAILURE_MARKERS` 一样，但词表不能共用：
#: 那份是 npm 的方言（``EAI_AGAIN`` / ``fetch failed``），这份是 pip 的
#: （``ProxyError`` / ``Read timed out`` / ``No matching distribution``）。
#:
#: 判据的意义：**只有网络类失败才值得换源**。实测踩到过一次 ——
#: ``pip install -r requirements-enhance.txt`` 在默认源上因为
#: "Cannot uninstall PyYAML 6.0.1, RECORD file not found（发行版装的）" 失败，
#: 换源当然还是同样失败，最后报给用户的却是"试了 3 个源都失败"，
#: 把人指向网络 —— 而真正要做的是 ``--ignore-installed PyYAML``。
NETWORK_FAILURE_MARKERS: Sequence[str] = (
    "ProxyError",
    "ConnectionError",
    "ConnectTimeout",
    "ReadTimeout",
    "Read timed out",
    "Temporary failure in name resolution",
    "Failed to establish a new connection",
    "Tunnel connection failed",
    "Connection broken",
    "No matching distribution found",
    "Could not find a version that satisfies",
    "SSLError",
    "CERTIFICATE_VERIFY_FAILED",
    "Network is unreachable",
    "超时",
)


def looks_like_network_failure(output: str) -> bool:
    """这段 pip 输出像不像网络问题（像 → 换源可能有救）。"""
    return any(marker in output for marker in NETWORK_FAILURE_MARKERS)


#: "这个包是发行版（apt/dnf）装的，pip 卸不掉"的签名。
#:
#: 形如::
#:
#:     ERROR: Cannot uninstall PyYAML 6.0.1, RECORD file not found.
#:            Hint: The package was installed by debian.
#:
#: 这在 Debian/Ubuntu 基础镜像上极其常见（PyYAML / setuptools / six 都可能中招），
#: 而且**一个包就能让整份 requirements 装不下去** —— 实测 requirements-enhance
#: 的 70 多个包全部因为 PyYAML 一个而回滚。
_DISTRO_OWNED_RE = re.compile(
    r"Cannot uninstall ([A-Za-z0-9._-]+)[^\n]*?RECORD file not found",
    re.IGNORECASE,
)


def distro_owned_blocker(output: str) -> Optional[str]:
    """从 pip 输出里认出"被发行版包挡住"的那个包名，认不出返回 ``None``。"""
    m = _DISTRO_OWNED_RE.search(output or "")
    return m.group(1) if m else None


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
    blocked_retried = False
    for idx, index_url in enumerate(candidates):
        cmd = list(base)
        if index_url:
            host = index_url.split("//", 1)[-1].split("/", 1)[0]
            cmd += ["-i", index_url, "--trusted-host", host]
        try:
            if stream:
                # stdout 继续直通终端（进度可见，这是"弱网别看着像卡死"那条的本意），
                # 但 stderr **必须捕获**：pip 的 ERROR 行走的是 stderr，
                # 原来这一路直接把 err 置空，于是 stderr_tail 永远是空的 ——
                # 失败时 UI 只能说一句"试了 N 个源都失败",真正的原因一个字都留不下。
                # 捕获之后当场回显，既没丢可见性，又留住了结构化的原因。
                proc = subprocess.run(
                    cmd, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", timeout=timeout
                )
                rc, err = proc.returncode, (proc.stderr or "")
                if rc != 0 and err:
                    sys.stderr.write(err)
                    sys.stderr.flush()
                err = err[-400:]
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

        # ── 自愈一级：被发行版包挡住 ────────────────────────────────────
        # 触发条件很窄（必须命中 _DISTRO_OWNED_RE），处理也很窄：只对**认出来的
        # 那一个包**加 --ignore-installed，不是全局加。全局加会让 pip 不再卸载
        # 任何旧版本，留下一堆半新半旧的并存安装 —— 那比装不上更难查。
        # 只重试一次；再失败就照常往下走（换源或如实报错）。
        blocker = distro_owned_blocker(err) if err and not blocked_retried else None
        if blocker:
            blocked_retried = True
            retry_cmd = list(cmd)
            retry_cmd.insert(retry_cmd.index("install") + 1, "--ignore-installed")
            retry_cmd.insert(retry_cmd.index("--ignore-installed") + 1, blocker)
            try:
                if stream:
                    proc = subprocess.run(
                        retry_cmd,
                        stderr=subprocess.PIPE,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=timeout,
                    )
                    rc2, err2 = proc.returncode, (proc.stderr or "")
                    if rc2 != 0 and err2:
                        sys.stderr.write(err2)
                        sys.stderr.flush()
                    err2 = err2[-400:]
                else:
                    proc = subprocess.run(
                        retry_cmd,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=timeout,
                    )
                    rc2, err2 = proc.returncode, (proc.stderr or "")[-400:]
            except Exception as exc:  # noqa: BLE001
                rc2, err2 = 1, f"{type(exc).__name__}: {exc}"
            if rc2 == 0:
                return InstallResult(
                    ok=True,
                    target=", ".join(pkgs),
                    index_used=index_url,
                    attempts=idx + 1,
                    healed=f"--ignore-installed {blocker}",
                )
            last_err = err2 or err

        # 不是网络问题就别再换源了 —— 换源救不了它，只会白跑两轮完整解析，
        # 然后把"试了 3 个源都失败"甩给用户，把人指向根本不相干的方向。
        if last_err and not looks_like_network_failure(last_err):
            return InstallResult(
                ok=False,
                target=", ".join(pkgs),
                index_used=index_url,
                attempts=idx + 1,
                stderr_tail=last_err,
                stopped_early=True,
            )
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
        # 镜像必须走 **CLI flag**，不能只靠环境变量。
        #
        # 实测（``npm config get electron_mirror`` 逐个验过）：
        #   ELECTRON_MIRROR=<url>            → 不生效，读回来还是 .npmrc 的值
        #   npm_config_electron_mirror=<url> → 不生效，同上
        #   --electron_mirror=<url>          → **生效**
        # 项目级 .npmrc 在这台机器上压过了环境变量，而 electron/.npmrc 正好钉死了
        # npmmirror。也就是说改成 flag 之前，三级"镜像轮换"其实三次都在用同一个源，
        # 抗单点这件事从来没真正成立过。
        #
        # 环境变量仍然一起设：@electron/get 自己也读 ELECTRON_MIRROR，
        # 两条都给上，不依赖单一机制。
        cli_mirror = [f"--electron_mirror={mirror}"] if mirror else []
        if mirror:
            env["ELECTRON_MIRROR"] = mirror
        try:
            rc = subprocess.run(
                [npm, "install", *NPM_NET_FLAGS, *cli_mirror, *extra], cwd=str(cwd), env=env, timeout=timeout
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
