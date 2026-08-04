"""launcher/env_check.py — 环境检查的**唯一**一份判据

为什么必须合并
--------------
在此之前，"这台机器能不能跑"有**两份互不知情的判断**：

* ``main.py:phase0_env_check()`` —— 正常启动路径走的那份；
* ``launch_desktop.py:phase0_environment_check()`` —— 它的 docstring 自称
  "精简版环境检查"，但它**不是** ``main.py`` 的子集。

"精简版"这个说法本身就不准确。逐行比对下来，两份各有对方没有的判据，而且
**同一个问题给出的答案会不一样**。下面这张表是实测的，不是估计：

============  ==========================================  ==========================================
检查项        ``main.py`` Phase 0                         ``launch_desktop`` phase0
============  ==========================================  ==========================================
Python 版本   只报版本，**没有下限门**                    要求 ``>= 3.10``，不满足直接 return
pip           ``which("pip") or which("pip3")``           ``sys.executable -m pip --version``
.env          存在 + 文件大小                             只看存在
API Key       ``.env`` **+ runtime/secrets.env**，         只读 ``os.environ``，用
              按 ``PLACEHOLDER_PREFIXES`` 过占位符        ``"your_"``/``"example"`` 子串过滤
npm           ``which`` 出**绝对路径**再取版本            只 ``which("npm")``
Node.js       查                                          **不查**
Electron      ``electron_package_intact()``（识别残缺）   ``node_modules/electron`` 目录是否存在
Ollama        只查装没装                                  装没装 + **在不在跑** + **有哪些模型**
就绪判据      pip / .env / npm 任一缺失即 not ready        python && pip && npm（**.env 不算**）
============  ==========================================  ==========================================

有几处的差别不是"详略"，是**对错**：

* **pip**：``which("pip")`` 找到的可能是**另一个解释器**的 pip（venv 没激活、
  或系统 pip 排在前面），它存在并不代表当前解释器装得上包。
  ``sys.executable -m pip`` 问的才是"**我这个** Python 能不能装东西"。
* **API Key**：密钥经面板保存后会被收敛进 ``runtime/secrets.env``（见
  ``core/config_store.py``），**不再明文留在 .env**。只读 ``os.environ`` 的那份
  在密钥已正确保存的情况下会一直报"没有 Key" —— 这正是 ``main.py`` 那侧修过的
  真 bug，而 ``launch_desktop`` 从来没跟上。
* **Electron**：只看目录存在，会漏掉**残缺安装**（``npm install`` 中途断掉：
  ``electron.cmd`` 存根在、``electron/cli.js`` 没了）。那种情况下会跳过安装、
  直接拉起 electron，然后崩。
* **npm**：Windows 上 npm 实际是 ``npm.cmd``，而 ``CreateProcess`` 不套用
  ``PATHEXT`` —— 传裸 ``"npm"`` 必抛 ``FileNotFoundError``。真机日志里
  "Node.js 有版本、npm 没版本"就是这个指纹。

合并原则：**逐行取更强的那个判据**，不是取并集也不是取交集
--------------------------------------------------------------
每一行都写明了取谁、为什么。取谁不取谁是**行为决定**，所以每一条都有对应的
测试钉住（``tests/test_launcher_env_check.py``），而不是留在注释里。

唯一一处**行为变化**要单独说：``main.py`` 原本没有 Python 版本下限门，合并后
有了（取 ``launch_desktop`` 的 ``>= 3.10``）。这是刻意的 —— 一个版本门是真实
有效的要素，没有它，3.9 上的失败会推迟到某个 import 处才炸，报错完全指不到
真正的原因。

刻意的边界：**本模块不打印**
----------------------------
它只产出事实（:class:`EnvReport` / :class:`~launcher.record.StepResult`）。
打印一律经 ``launcher/ui.py`` 那个唯一咽喉。这样同一份判据能同时喂给终端、
``startup.json`` 和日志，而不是像以前那样"判断完就只剩一行彩色文本"。
"""

from __future__ import annotations

import dataclasses
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from launcher.record import Column, Status, StepResult

#: Python 版本下限。取自 ``launch_desktop.phase0_environment_check``（两份里
#: 唯一有版本门的那份）。CI 与 mypy 都按 3.11 跑，但 3.10 是**能跑**的下限，
#: 收紧到 3.11 属于超出"合并"范围的行为变更，不在这里做。
MIN_PYTHON: Tuple[int, int] = (3, 10)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
ELECTRON_DIR = PROJECT_ROOT / "electron"

#: 判定一个配置键"是不是密钥"用的子串。与两份原实现保持一致。
_KEY_TOKENS = ("API_KEY", "KEY")


@dataclasses.dataclass(frozen=True)
class EnvReport:
    """一次环境检查的全部事实。

    字段是**事实**，不是显示文本；``ready`` 是由事实算出来的结论。
    """

    python_version: str
    python_ok: bool
    python_executable: str

    pip_ok: bool
    pip_version: str = ""

    env_exists: bool = False
    env_size_bytes: int = 0

    api_keys_configured: int = 0

    npm_installed: bool = False
    npm_version: str = ""
    npm_path: Optional[str] = None

    node_installed: bool = False
    node_version: str = ""

    electron_deps_ok: bool = False
    electron_probe: str = ""
    """``"intact"``（完整性检查通过）/ ``"partial"`` / ``"missing"`` /
    ``"fallback-dir-exists"``（完整性检查不可用，退化成看目录）。"""

    ollama_installed: bool = False
    ollama_running: bool = False
    ollama_models: List[str] = dataclasses.field(default_factory=list)

    @property
    def model_available(self) -> bool:
        return bool(self.ollama_models)

    @property
    def has_api_key(self) -> bool:
        return self.api_keys_configured > 0

    @property
    def ready(self) -> bool:
        """能不能继续启动。

        取两份判据里**更严**的那个组合：Python 版本门（来自 launch_desktop）
        + pip + npm（两份都要）。

        ``.env`` **不进** ready —— 这是取 ``launch_desktop`` 的判断而不是
        ``main.py`` 的。理由是实证的：``main.py`` 自己的 Phase 2 就有
        "``.env`` 不存在则从 ``.env.example`` 复制一份"的自愈（见
        ``phase2_ensure_deps``），把一个**下一步就会自动补上**的东西算进
        "不能启动"，只会让启动在可以自愈的情况下白白终止。
        """
        return self.python_ok and self.pip_ok and self.npm_installed

    # ── 输出适配 ──────────────────────────────────────────────────────

    def to_status_dict(self) -> Dict[str, Any]:
        """产出两个老调用方都认识的 dict（键取**并集**）。

        为什么是并集而不是挑一套：``main.py:phase2_ensure_deps`` 读
        ``pip_ok`` / ``env_exists`` / ``npm_installed`` / ``electron_deps_ok`` /
        ``ollama_installed``，``launch_desktop`` 那侧读 ``python_ok`` /
        ``has_api_key`` / ``ollama_running`` / ``model_available``。少给任何一
        个键，对应调用点就会静默走进 ``.get()`` 的 ``None`` 分支 —— 那比报错更
        难查。

        返回的是**可变** dict：两侧都会在自愈成功后回写（例如装完 npm 之后
        ``env_status["npm_installed"] = True``），这个行为必须保住。
        """
        return {
            "ready": self.ready,
            # main.py 侧
            "python_version": self.python_version,
            "pip_ok": self.pip_ok,
            "env_exists": self.env_exists,
            "api_keys_configured": self.api_keys_configured,
            "npm_installed": self.npm_installed,
            "node_installed": self.node_installed,
            "electron_deps_ok": self.electron_deps_ok,
            "ollama_installed": self.ollama_installed,
            # launch_desktop 侧
            "python_ok": self.python_ok,
            "has_api_key": self.has_api_key,
            "ollama_running": self.ollama_running,
            "model_available": self.model_available,
        }

    def to_steps(self) -> List[StepResult]:
        """产出可直接交给 ``launcher.ui`` 渲染的事实行。

        状态语义：能跑但打了折 → ``DEGRADED``；缺了就跑不了 → ``FAILED``。
        没有可靠建议的项 ``hint`` 留 ``None``，**不编**。
        """
        steps: List[StepResult] = []

        def add(name: str, status: Status, value: str = "", hint: Optional[str] = None, **detail: Any) -> None:
            steps.append(StepResult(column=Column.ENV, name=name, status=status, value=value, hint=hint, detail=detail))

        add(
            "Python",
            Status.OK if self.python_ok else Status.FAILED,
            self.python_version,
            None if self.python_ok else f"需要 Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+",
            executable=self.python_executable,
            min_required=f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}",
        )
        add(
            "pip",
            Status.OK if self.pip_ok else Status.FAILED,
            self.pip_version,
            None if self.pip_ok else f"{sys.executable} -m ensurepip --upgrade",
        )
        add(
            ".env 配置文件",
            Status.OK if self.env_exists else Status.DEGRADED,
            f"{self.env_size_bytes // 1024 or 1}KB" if self.env_exists else "",
            None if self.env_exists else "将从 .env.example 复制（依赖阶段自动完成）",
            size_bytes=self.env_size_bytes,
        )
        add(
            "API Key",
            Status.OK if self.has_api_key else Status.DEGRADED,
            f"{self.api_keys_configured} 个" if self.has_api_key else "未配置",
            None if self.has_api_key else "在面板里填，或编辑 .env",
            count=self.api_keys_configured,
        )
        add(
            "npm",
            Status.OK if self.npm_installed else Status.FAILED,
            self.npm_version,
            None if self.npm_installed else "https://nodejs.org",
            path=self.npm_path,
        )
        add(
            "Node.js",
            Status.OK if self.node_installed else Status.DEGRADED,
            self.node_version,
            None if self.node_installed else "https://nodejs.org",
        )
        add(
            "Electron 依赖",
            Status.OK if self.electron_deps_ok else Status.DEGRADED,
            "已就位" if self.electron_deps_ok else self.electron_probe,
            None if self.electron_deps_ok else "依赖阶段会自动 npm install",
            probe=self.electron_probe,
        )
        if self.ollama_running:
            ollama_status, ollama_value, hint = Status.OK, "运行中", None
        elif self.ollama_installed:
            ollama_status, ollama_value, hint = Status.DEGRADED, "已安装，未运行", "ollama serve"
        else:
            ollama_status, ollama_value, hint = Status.DEGRADED, "未安装", "https://ollama.com/download"
        add("Ollama", ollama_status, ollama_value, hint, models=list(self.ollama_models))
        if self.ollama_models:
            add("本地模型", Status.OK, "、".join(self.ollama_models[:3]), None, all_models=list(self.ollama_models))
        return steps


# ── 逐项探测（每个都是纯函数：只读环境，不打印、不改环境） ─────────────


def _probe_python() -> Tuple[str, bool, str]:
    v = sys.version_info
    return f"{v.major}.{v.minor}.{v.micro}", (v.major, v.minor) >= MIN_PYTHON, sys.executable


def _probe_pip() -> Tuple[bool, str]:
    """问的是"**当前解释器**能不能装包"，不是"PATH 上有没有个叫 pip 的东西"。

    取 ``launch_desktop`` 的判据。见模块头 pip 那一条。
    """
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except Exception:
        return False, ""
    if r.returncode != 0:
        return False, ""
    # "pip 24.0 from /usr/lib/python3/dist-packages/pip (python 3.11)" → "24.0"
    parts = (r.stdout or "").split()
    return True, parts[1] if len(parts) > 1 else ""


def _probe_api_keys(env_file: Optional[Path] = None) -> int:
    """.env **与** runtime/secrets.env 合起来数，并过滤占位符。

    取 ``main.py`` 的判据。见模块头 API Key 那一条。

    ``env_file`` 由调用方传入（默认用模块常量）：**路径的所有权在调用方**。
    否则同一个 ``.env`` 会在 ``main`` / ``launch_desktop`` / 这里各有一份模块级
    常量，改一处漏两处 —— 那正是这次统一要消掉的东西。它同时也是测试注入点。
    """
    env_path = env_file if env_file is not None else ENV_FILE
    seen: set = set()
    try:
        from core.credential_vault import PLACEHOLDER_PREFIXES
    except Exception:
        PLACEHOLDER_PREFIXES = ("your_", "example", "changeme", "<")  # type: ignore[assignment]

    def _accept(key: str, val: str) -> bool:
        val = (val or "").strip()
        return (
            bool(val)
            and not val.lower().startswith(PLACEHOLDER_PREFIXES)
            and any(t in key.upper() for t in _KEY_TOKENS)
        )

    try:
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    key, _, val = line.partition("=")
                    if _accept(key.strip(), val):
                        seen.add(key.strip().upper())
    except Exception:
        pass

    try:
        from core.config_store import get_config_store

        for key, val in get_config_store().read_secrets().items():
            if _accept(key, val):
                seen.add(key.upper())
    except Exception:
        pass

    return len(seen)


def _probe_npm() -> Tuple[bool, str, Optional[str]]:
    """用 ``which`` 解析出的**绝对路径**调用，不传裸 ``"npm"``。

    取 ``main.py`` 的判据。见模块头 npm 那一条（Windows ``npm.cmd`` / PATHEXT）。
    """
    exe = shutil.which("npm")
    if not exe:
        return False, "", None
    try:
        r = subprocess.run(
            [exe, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10
        )
        return True, (r.stdout.strip() if r.returncode == 0 else ""), exe
    except Exception:
        return True, "", exe


def _probe_node() -> Tuple[bool, str]:
    exe = shutil.which("node")
    if not exe:
        return False, ""
    try:
        r = subprocess.run(
            [exe, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10
        )
        return True, (r.stdout.strip() if r.returncode == 0 else "")
    except Exception:
        return True, ""


def _probe_electron(npm_ok: bool, electron_dir: Optional[Path] = None) -> Tuple[bool, str]:
    """完整性检查，不是"目录在不在"。

    取 ``main.py`` 的判据。见模块头 Electron 那一条（残缺安装）。
    ``electron_package_intact`` 不可用时才退化成看目录，并如实标记
    ``"fallback-dir-exists"`` —— 让人知道这一次的结论**没那么硬**。
    """
    root = electron_dir if electron_dir is not None else ELECTRON_DIR
    if not npm_ok:
        return False, "missing"
    try:
        from core.electron_launch_guard import electron_package_intact

        if electron_package_intact(str(root)):
            return True, "intact"
        return False, "partial" if (root / "node_modules").exists() else "missing"
    except Exception:
        exists = (root / "node_modules").exists()
        return exists, "fallback-dir-exists" if exists else "missing"


def _probe_ollama() -> Tuple[bool, bool, List[str]]:
    """装没装 + 在不在跑 + 有哪些模型。

    后两项取 ``launch_desktop`` 的判据 —— ``main.py`` 只查了"装没装"，
    而"装了但没起来"和"起来了但一个模型都没有"是完全不同的处境。
    """
    if shutil.which("ollama") is None:
        return False, False, []
    try:
        r = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8
        )
    except Exception:
        return True, False, []
    if r.returncode != 0:
        return True, False, []
    models: List[str] = []
    for idx, line in enumerate((r.stdout or "").strip().splitlines()):
        if not line.strip():
            continue
        if idx == 0 and line.split()[:1] == ["NAME"]:  # 跳过表头
            continue
        models.append(line.split()[0])
    return True, True, models


def check_environment(
    *, env_file: Optional[Path] = None, electron_dir: Optional[Path] = None
) -> EnvReport:
    """跑完整套环境检查，返回事实。**不打印任何东西。**

    Args:
        env_file:     ``.env`` 的路径。**由调用方给**（``main.py`` 与
                      ``launch_desktop.py`` 各自持有自己的 ``ENV_FILE``），不给
                      则用模块常量。路径的所有权留在调用方，是为了不让同一个
                      文件在三个模块里各有一份常量 —— 改一处漏两处正是这次
                      统一要消掉的东西。
        electron_dir: 同理，Electron 目录。
    """
    py_version, py_ok, py_exe = _probe_python()
    if not py_ok:
        # 版本不达标时提前返回：后面的探测（import core.*）在旧版本上本来就
        # 可能因语法/类型写法直接炸，那种崩溃会盖掉"你的 Python 太老了"这个
        # 唯一有用的信息。这是 launch_desktop 的 early-return，保留。
        return EnvReport(python_version=py_version, python_ok=False, python_executable=py_exe, pip_ok=False)

    pip_ok, pip_version = _probe_pip()
    npm_ok, npm_version, npm_path = _probe_npm()
    node_ok, node_version = _probe_node()
    electron_ok, electron_probe = _probe_electron(npm_ok, electron_dir)
    ollama_installed, ollama_running, ollama_models = _probe_ollama()

    env_path = env_file if env_file is not None else ENV_FILE
    env_exists = env_path.exists()
    return EnvReport(
        python_version=py_version,
        python_ok=True,
        python_executable=py_exe,
        pip_ok=pip_ok,
        pip_version=pip_version,
        env_exists=env_exists,
        env_size_bytes=env_path.stat().st_size if env_exists else 0,
        api_keys_configured=_probe_api_keys(env_path),
        npm_installed=npm_ok,
        npm_version=npm_version,
        npm_path=npm_path,
        node_installed=node_ok,
        node_version=node_version,
        electron_deps_ok=electron_ok,
        electron_probe=electron_probe,
        ollama_installed=ollama_installed,
        ollama_running=ollama_running,
        ollama_models=ollama_models,
    )


__all__ = [
    "MIN_PYTHON",
    "EnvReport",
    "check_environment",
]
