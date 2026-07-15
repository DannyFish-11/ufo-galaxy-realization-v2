#!/usr/bin/env python3
# PR-WIN-ENCODING: Force UTF-8 on Windows to prevent UnicodeEncodeError in logs
import sys
import os

# ── .env 加载:必须在任何读取 os.environ 的代码之前完成 ──────────────────
# python-dotenv 早就在 requirements 里锁了版本,但全仓库范围内从未被真正调用
# 过——.env 文件从来没有被加载进 os.environ。真机复现过:「模型」tab 存的任何
# API Key(不止 DeepSeek，OpenAI/Anthropic/Gemini/Groq/... 全部受影响)在保存
# 当次生效(setConfig 会同步写 os.environ),但重启新进程后——凡是代码直接读
# os.environ(而不是全部经过 core.unified_config 的间接路径)——统统读不到，
# 表现为"存了，重启后又没了"。这里在进程最早期加载 .env，且 override=False
# (不覆盖已存在的真实 shell/系统环境变量，尊重用户显式导出的优先级更高)。
try:
    from dotenv import dotenv_values
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    # 关键:不能用 load_dotenv() 整个灌进去——设置面板自动生成的 .env 会把
    # 【全部】schema 键写成 KEY=(空值)。空字符串一旦进了 os.environ,就会把
    # 代码里的默认值顶掉:os.environ.get("OLLAMA_URL", "http://localhost:11434")
    # 在 OLLAMA_URL="" 存在时返回的是 ""，不是默认值!真机复现过的一整串症状
    # 都源于此——LocalBrainManager 拿着空 URL ping Ollama(报"Request URL is
    # missing an 'http://' or 'https://' protocol"、Ollama 明明在跑却判"服务
    # 未响应/模型未就绪")、Redis "must specify scheme"、NATS "invalid
    # hostname"。这里改为只加载【非空】值,空值视同未配置,让代码默认值生效。
    # 另一类毒值:python-dotenv 会把「KEY=   # 注释」这种【空值+行内注释】整段
    # 注释当成值(实测 1.2.2:OLLAMA_URL= # e.g. http://... → '# e.g. http://...'),
    # 经 normalize 补协议头后变成 http://#... 的怪 URL,骗过全部 startswith 检查。
    # 值以 # 开头一律视同未配置(合法配置值不可能以 # 开头)。
    for _k, _v in (dotenv_values(_env_path) or {}).items():
        if _v and not _v.lstrip().startswith("#") and _k not in os.environ:
            os.environ[_k] = _v
except Exception:
    pass

# ── 第三方库的已知噪音告警降噪 ─────────────────────────────────────────────
# 真机启动日志里有几条来自【第三方依赖】的 UserWarning,与 Galaxy 自身无关、
# 用户既无法也无需处理,却每次启动都刷屏。用精确匹配把这几条静音(只针对已知
# 来源,不做全局吞并,避免掩盖真正的告警):
#   - webrtcvad → "pkg_resources is deprecated"(setuptools 弃用,第三方未适配)
#   - pywinauto → "Revert to STA COM threading mode"(Windows COM 线程模式提示)
import warnings as _warnings
try:
    _warnings.filterwarnings("ignore", message=r".*pkg_resources is deprecated.*")
    _warnings.filterwarnings("ignore", message=r".*Revert to STA COM threading mode.*")
    _warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"webrtcvad.*")
except Exception:
    pass

if sys.platform == "win32":
    # Set console to UTF-8 mode (Python 3.7+)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    # Force logging StreamHandler to use UTF-8 as well
    # CRITICAL: must reconfigure BOTH stdout AND stderr — logging uses stderr by default
    try:
        import io
        if hasattr(sys.stdout, "buffer"):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
        if hasattr(sys.stderr, "buffer"):
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass
    # Also set environment variable for subprocesses
    os.environ["PYTHONIOENCODING"] = "utf-8:replace"
    # PR-D7: Set process priority (Windows only)
    try:
        import psutil
        p = psutil.Process()
        p.nice(psutil.HIGH_PRIORITY_CLASS)
    except Exception:
        pass

# ── HuggingFace 下载:必须在任何 HF 库(transformers/sentence_transformers/
#    huggingface_hub/faster_whisper)被 import 之前设置,否则 HF_ENDPOINT 被库缓存,
#    镜像不生效 → 退回 huggingface.co,在国内被墙 → 每个文件 5 次重试 ×指数退避 →
#    嵌入器/Whisper 加载能卡 4 分钟,把 /chat/stream 拖到 270s(实测)。
# 这里在进程最早期把端点指向国内镜像并把超时/重试压到最小,让"连不上"秒失败降级,
# 而不是卡几分钟。可用 GALAXY_HF_MIRROR=0 关闭镜像。
try:
    os.environ.setdefault("HF_ENDPOINT", os.environ.get("GALAXY_HF_ENDPOINT", "https://hf-mirror.com"))
    if os.environ.get("GALAXY_HF_MIRROR", "1").strip().lower() in ("0", "false", "no", "off"):
        os.environ.pop("HF_ENDPOINT", None)
    # 快速失败:单次 etag/连接超时压到 3s,避免默认 10s×5 次重试的长时间阻塞。
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "3")
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "10")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
except Exception:
    pass

"""
Galaxy-Nexus 星枢 — System Orchestrator
========================================

**SYSTEM_ORCHESTRATOR_AUTHORITY** — ``main.py:SYSTEM_ORCHESTRATOR``
--------------------------------------------------------------------
This file is the **canonical system orchestrator** for Galaxy-Nexus.
``python main.py`` is the official startup path.

Staged bring-up contract (PR-2)
--------------------------------
.. code-block:: text

    Phase 1 — LOAD_CONFIG           Load unified configuration baseline
    Phase 2 — RESOLVE_MODE          Resolve current system mode
    Phase 3 — ENV_CHECKS            Environment / bootstrap checks
    Phase 4 — BACKGROUND_SUBSYSTEMS Background subsystem bring-up hooks
    Phase 5 — RUNTIME_SUBJECT       Runtime subject bring-up hooks
    Phase 6 — DESKTOP_SURFACE       Desktop surface bring-up hooks
    Phase 7 — READINESS_SUMMARY     Final readiness summary

``unified_launcher.py`` is a **subordinate** launcher component invoked during
Phase 4–6.  It is NOT a competing top-level startup authority.

Subject lifecycle authority
---------------------------
- :class:`~core.desktop_presence_runtime.DesktopPresenceRuntime` — outer shell
- :class:`~core.openclawd.OpenClawd` — subject core

Usage
-----
    python main.py              # Start complete Galaxy-Nexus system
    python main.py --setup      # Run configuration wizard
    python main.py --status     # Show system status
    python main.py --help       # Show all startup options

All startup options are forwarded to ``unified_launcher.py`` (subordinate
component) after the orchestrator completes its staged pre-flight sequence.
"""

import os
import asyncio
import sys
import subprocess
import logging
import argparse
from pathlib import Path

from core.ascii_art import print_banner, print_section_header

# ── Phase output helpers ──────────────────────────────────
_PHASE_WIDTH = 60


def print_phase(title: str) -> None:
    """打印阶段小标题。

    统一走 core.cli_render（与启动后半段同一套 clig.dev 风格：细线 + 干净标题，
    而非旧的 ═══×60 大框）——让【整个克隆界面】前后一致。cli_render 不可用时兜底回旧风格。
    """
    try:
        from core import cli_render as r
        r.section(title)
    except Exception:
        print_section_header(title)  # 极端环境兜底
    # PR-WIN-ENCODING: logger may still use cp1252 even after SafeStreamHandler
    try:
        logger.info("[Phase] %s", title)
    except UnicodeEncodeError:
        pass


def print_item(name: str, status: str = "ok", detail: str = "") -> None:
    """打印阶段内的状态项。

    统一走 core.cli_render 的子项行（✓/⚠/✗/· + 按显示宽度对齐 + 颜色可降级），
    与启动后半段完全一致。cli_render 不可用时兜底回旧的 [OK]/[WARN] ASCII。

    Args:
        name: Item description.
        status: "ok" | "warn" | "error" | "info".
        detail: Optional detail text shown dimmed.
    """
    _status_map = {"ok": "ok", "warn": "warn", "error": "fail", "info": "info"}
    printed = False
    try:
        from core import cli_render as r
        # 用 phase()(2 格缩进,标签第 4 列)而非 detail()(6 格缩进)——让 Phase 0/1/2
        # 的状态项与「系统启动」后的运行时项(核心服务/基础设施/... 也走 phase)以及
        # ▶ 启动行处在【同一列】。此前 Phase 段 6 格、运行时段 2 格,对勾对不齐。
        r.phase(name, detail, _status_map.get(status, "info"))
        printed = True
    except Exception:
        printed = False
    if not printed:
        # 兜底：旧风格 ASCII（cli_render 不可用时），Windows cp1252 安全打印
        icon = {"ok": "[OK]", "warn": "[WARN]", "error": "[ERR]", "info": "[INFO]"}.get(status, "[*]")
        line = f"  {icon} {name}" + (f"  ({detail})" if detail else "")
        try:
            print(line)
        except UnicodeEncodeError:
            try:
                print(line.encode("cp1252", errors="replace").decode("cp1252"))
            except Exception:
                pass
    # PR-WIN-ENCODING: wrap logger to suppress cp1252 UnicodeEncodeError
    try:
        logger.info("[%s] %s %s", status.upper(), name, detail)
    except UnicodeEncodeError:
        pass


from entrypoint_role_contract import (
    EntrypointRole,
    MAIN_ENTRY_ID,
    assert_single_unique_main_entrypoint,
    ensure_entrypoint_role,
)

# ---------------------------------------------------------------------------
# Bootstrap: project root + sys.path
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

ENV_FILE = Path(".env")
ENV_EXAMPLE = Path(".env.example")
ELECTRON_DIR = Path("electron")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

from logging.handlers import RotatingFileHandler


class SafeStreamHandler(logging.StreamHandler):
    """Windows-safe StreamHandler with UTF-8 encoding for CJK characters.

    On Windows, the default console encoding (cp1252 / cp936 / cp950)
    cannot encode certain CJK characters, causing::

        UnicodeEncodeError: 'charmap' codec can't encode characters ...

    This handler re-wraps *stream.buffer* with an explicit UTF-8
    TextIOWrapper so Chinese log messages are emitted safely.
    Linux / macOS keep the default behaviour (usually UTF-8 already).
    """

    def __init__(self, stream=None):
        super().__init__(stream)
        # Only patch on Windows where the console encoding is limited.
        if sys.platform == "win32" and hasattr(self.stream, "buffer"):
            import io

            self.stream = io.TextIOWrapper(
                self.stream.buffer,
                encoding="utf-8",
                errors="replace",
                line_buffering=True,
            )

    def emit(self, record):
        """Override emit to catch UnicodeEncodeError on Windows."""
        try:
            super().emit(record)
        except UnicodeEncodeError:
            # Fallback: encode message with replace, then write bytes
            try:
                msg = self.format(record) + self.terminator
                self.stream.buffer.write(msg.encode("utf-8", errors="replace"))
            except Exception:
                pass


# PR-D6: Log rotation (10MB per file, keep 5 backups)
log_dir = PROJECT_ROOT / "logs"
log_dir.mkdir(exist_ok=True)

# SECURITY: Only configure logging if no handlers exist yet.
# Multiple entry points (main.py, lumiv_daemon.py, system_manager.py)
# call basicConfig; repeated calls are no-ops after the first.
if not logging.getLogger().handlers:
    handler = RotatingFileHandler(
        str(log_dir / "lumiv.log"), maxBytes=10 * 1024 * 1024, backupCount=5,
        encoding="utf-8",
    )
    _console = SafeStreamHandler()
    _console.setLevel(logging.WARNING)  # console只显示警告/错误；详情在 logs/lumiv.log
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=[handler, _console],
    )
logger = logging.getLogger("Galaxy")

# 静默 URL 哨兵:给 httpx 加一层【只观测、不干预】的薄壳,任何缺 http(s):// 协议头的
# 请求 URL(那个 "Request URL is missing protocol" 的根源)一出现就把精确调用栈记进日志。
# 平时零输出、零行为影响;装不上也静默兜底,绝不影响主进程。
try:
    from core.ollama_url_sentinel import install as _install_url_sentinel
    _install_url_sentinel()
except Exception:  # noqa: BLE001
    pass

# Health / validation tracking (non-strict mode diagnostics)
_health_status: str = "unknown"
_failed_validations: list = []

# ---------------------------------------------------------------------------
# Authority declaration — referenced by validate_runtime.py and CI guardrails
# ---------------------------------------------------------------------------

SYSTEM_ORCHESTRATOR_AUTHORITY: str = (
    "main.py:SYSTEM_ORCHESTRATOR — canonical staged bring-up contract (PR-2)"
)


# ---------------------------------------------------------------------------
# Orchestrator bring-up sequence
# ---------------------------------------------------------------------------

def _is_strict_preflight() -> bool:
    """Return True when GALAXY_STRICT_PREFLIGHT is set to a truthy value.

    Set ``GALAXY_STRICT_PREFLIGHT=1`` (or ``true``) to make **any** preflight
    exception or Phase-3 CRITICAL failure abort startup rather than proceeding
    in degraded mode.  Useful for production deployments and CI pipelines
    where silent-success startup is unacceptable.
    """
    return os.environ.get("GALAXY_STRICT_PREFLIGHT", "").lower() in ("1", "true", "yes")


def _run_orchestrator_preflight() -> bool:
    """Execute the staged pre-flight bring-up sequence (Phases 1–7).

    Returns ``True`` if the system is ready to proceed to the full async
    bring-up via ``unified_launcher``, ``False`` on hard failure.

    Logs one line per phase so startup logs reflect clear staged bring-up.

    Strict mode
    ~~~~~~~~~~~
    When ``GALAXY_STRICT_PREFLIGHT=1`` any exception raised by the orchestrator
    itself is treated as a hard failure (returns ``False``) rather than being
    silently swallowed.  This prevents critically broken environments from
    appearing healthy at startup.
    """
    global _health_status, _failed_validations
    strict = _is_strict_preflight()
    try:
        from core.system_orchestrator import SystemOrchestrator
        orch = SystemOrchestrator(continue_on_failure=False, strict_preflight=strict)
        summary = orch.run_startup_sequence()
        logger.info("Orchestrator bring-up complete:\n%s", summary)
        _health_status = "healthy"
        _failed_validations.clear()
        return summary.is_ready()
    except Exception as exc:
        exc_str = str(exc)
        _failed_validations.append(exc_str)
        if strict:
            logger.critical(
                "Startup validation failed (GALAXY_STRICT_PREFLIGHT=1 — hard failure): %s",
                exc,
                exc_info=True,
            )
            _health_status = "failed"
            return False
        # Non-strict: log FULL exception details, then continue degraded
        logger.critical(
            "Startup validation failed: %s",
            exc,
            exc_info=True,
        )
        logger.warning(
            "CONTINUING IN DEGRADED MODE — some security features may not work correctly. "
            "Set GALAXY_STRICT_PREFLIGHT=1 to abort startup on validation failures."
        )
        _health_status = "degraded"
        # Degraded but non-fatal — proceed with bring-up
        return True


def phase0_env_check() -> dict:
    """Phase 0: Environment check — Python, .env, API Key, pip, npm.

    Returns:
        Status dict with keys like python_version, pip_ok, env_exists,
        api_keys_configured, npm_installed, electron_deps_ok, ollama_installed.
    """
    import shutil
    import subprocess as sp

    status: dict[str, object] = {"ready": True}

    # Python version
    py_ver = sys.version_info
    py_str = f"{py_ver.major}.{py_ver.minor}.{py_ver.micro}"
    print_item(f"Python {py_str}", "ok", sys.executable)
    status["python_version"] = py_str

    # pip
    pip_ok = shutil.which("pip") is not None or shutil.which("pip3") is not None
    if pip_ok:
        print_item("pip", "ok")
    else:
        print_item("pip 未安装", "warn")
        status["ready"] = False
    status["pip_ok"] = pip_ok

    # .env
    env_exists = ENV_FILE.exists()
    if env_exists:
        size = ENV_FILE.stat().st_size
        print_item(".env 配置文件", "ok", f"{size // 1024 or 1}KB")
    else:
        print_item(".env 未找到", "warn")
        status["ready"] = False
    status["env_exists"] = env_exists

    # API Key check
    api_count = 0
    try:
        env_text = ENV_FILE.read_text() if env_exists else ""
        for line in env_text.splitlines():
            if "=" in line and not line.startswith("#"):
                key, _, val = line.partition("=")
                if val.strip() and any(k in key.upper() for k in ["API_KEY", "KEY"]):
                    api_count += 1
    except Exception:
        pass
    if api_count > 0:
        print_item(f"API Key 已配置 ({api_count}个)", "ok")
    else:
        print_item("API Key 未配置", "warn", "请编辑 .env 添加你的 Key")
    status["api_keys_configured"] = api_count

    # npm
    npm_ok = shutil.which("npm") is not None
    if npm_ok:
        try:
            rc = sp.run(["npm", "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)
            npm_ver = rc.stdout.strip() if rc.returncode == 0 else "?"
            print_item("npm", "ok", npm_ver)
        except Exception:
            print_item("npm", "ok")
    else:
        print_item("npm 未安装", "warn")
        status["ready"] = False
    status["npm_installed"] = npm_ok

    # Node.js
    node_ok = shutil.which("node") is not None
    if node_ok:
        try:
            rc = sp.run(["node", "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)
            node_ver = rc.stdout.strip() if rc.returncode == 0 else "?"
            print_item("Node.js", "ok", node_ver)
        except Exception:
            print_item("Node.js", "ok")
    else:
        print_item("Node.js 未安装", "warn")
    status["node_installed"] = node_ok

    # Electron deps —— 判定"完整"而非仅"node_modules 目录存在"。
    # 只看目录存在会漏掉【残缺安装】(npm install 中断:electron.cmd 存根在、但
    # electron/cli.js 缺失),那样会跳过安装、直接拉起 electron 然后崩。用
    # electron_package_intact 做完整性检查:缺失或残缺都判 False,让下面的
    # `npm install`(正常下载)照跑并把缺的补齐——这就是"正常下载 + 缺失/残缺才补"。
    if npm_ok:
        try:
            from core.electron_launch_guard import electron_package_intact
            electron_deps_ok = electron_package_intact(str(ELECTRON_DIR))
        except Exception:
            electron_deps_ok = (ELECTRON_DIR / "node_modules").exists()
    else:
        electron_deps_ok = False
    status["electron_deps_ok"] = electron_deps_ok

    # Ollama
    ollama_ok = shutil.which("ollama") is not None
    if ollama_ok:
        print_item("Ollama 已安装", "ok")
    else:
        print_item("Ollama 未安装", "warn")
    status["ollama_installed"] = ollama_ok

    return status


def phase2_ensure_deps(env_status: dict) -> bool:
    """Phase 2: Ensure dependencies — pip / npm / Electron / Ollama / Voice.

    Auto-fixes missing dependencies including:
    - pip itself (ensurepip / get-pip.py)
    - Python core packages
    - Node.js + npm (auto-download)
    - Electron frontend deps
    - Ollama model auto-pull
    - Voice deps (required): pvporcupine, webrtcvad, faster-whisper, pyaudio

    Args:
        env_status: Status dict from phase0_env_check().

    Returns:
        True if all critical dependencies are ready.
    """
    import shutil
    import subprocess as sp

    all_ok = True

    # 弱网加固(与 2.4 Electron/npm 同一套思路):pip 安装
    #   ①【流式输出】不 capture,进度可见——避免"看着像卡死";
    #   ②默认源失败后逐个回退国内镜像(清华 → 阿里云),抗单点;
    #   ③pip 自带重试/超时放宽。
    _PIP_INDEX_CANDIDATES: list = [
        None,  # 默认源(尊重用户已配置的 pip.conf / 环境)
        "https://pypi.tuna.tsinghua.edu.cn/simple",
        "https://mirrors.aliyun.com/pypi/simple/",
    ]

    def _run_pip_install(pkgs: list, timeout: int = 900) -> bool:
        """逐镜像候选安装 pkgs,全部失败才返回 False(诚实上报)。"""
        base = [sys.executable, "-m", "pip", "install",
                "--retries", "3", "--timeout", "60"] + pkgs
        for idx, index_url in enumerate(_PIP_INDEX_CANDIDATES):
            cmd = list(base)
            if index_url:
                cmd += ["-i", index_url]
                print_item(f"回退镜像源 {idx}/{len(_PIP_INDEX_CANDIDATES) - 1}",
                           "warn", index_url)
            try:
                if sp.run(cmd, timeout=timeout).returncode == 0:
                    return True
            except sp.TimeoutExpired:
                print_item(f"pip 安装超时({timeout}s)", "warn",
                           "镜像候选轮换中" if idx < len(_PIP_INDEX_CANDIDATES) - 1 else "")
            except Exception as exc:
                print_item(f"pip 安装异常: {exc}", "warn")
        return False

    # 2.0 Ensure pip is available
    if not env_status.get("pip_ok"):
        print_item("pip 未安装，正在修复...", "warn")
        pip_fixed = False
        # Method 1: ensurepip
        try:
            rc = sp.run(
                [sys.executable, "-m", "ensurepip", "--upgrade"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
            ).returncode
            if rc == 0:
                pip_fixed = True
                print_item("pip 已通过 ensurepip 安装", "ok")
        except Exception:
            pass
        # Method 2: get-pip.py
        if not pip_fixed:
            try:
                import tempfile
                get_pip_tmp = os.path.join(tempfile.gettempdir(), "get-pip.py")
                rc = sp.run([
                    sys.executable, "-c",
                    f"import urllib.request; "
                    f"urllib.request.urlretrieve('https://bootstrap.pypa.io/get-pip.py', r'{get_pip_tmp}')",
                ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30).returncode
                if rc == 0:
                    rc2 = sp.run(
                        [sys.executable, get_pip_tmp],
                        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                    ).returncode
                    if rc2 == 0:
                        pip_fixed = True
                        print_item("pip 已通过 get-pip.py 安装", "ok")
            except Exception:
                pass
        if not pip_fixed:
            print_item("pip 安装失败，请手动安装", "error")
            all_ok = False

    # 2.1 Python core dependencies
    print_item("检查 Python 核心依赖...", "ok")
    core_deps_missing = []
    core_modules = {
        "fastapi": "fastapi",
        "pydantic": "pydantic",
        "httpx": "httpx",
        "uvicorn": "uvicorn",
        "starlette": "starlette",
        "ollama": "ollama",
        "nats": "nats-py",
        "websockets": "websockets",
        # 依赖审计补齐:被核心能力真实 import,补进自动安装(与 requirements.txt 一致)
        "jsonschema": "jsonschema",          # 事件总线 schema 校验
        "huggingface_hub": "huggingface-hub",  # 本地模型 HF 下载 + Ollama 回退
        "tqdm": "tqdm",                       # 模型下载进度条
        # 语音输出(TTS)默认引擎。此前不在自动安装名单、requirements-windows.txt
        # 也没有 → 真机全新克隆缺包,speech_output 每次合成静默失败,表现为
        # "回复文字出来了、一句话都不说"。包本身很小(纯 HTTP 客户端)。
        "edge_tts": "edge-tts",
        # 分布式追踪(OpenTelemetry SDK):core/otel_tracing.py 默认跟随跨设备开关
        # 而开(跨设备默认开),但只有这里真的把包装上,"默认开"才不只是纸面上的
        # 开关——否则每次全新 clone 后 import 失败,仍会静默降级为 no-op、启动摘要
        # 里打"otel_tracing: skipped"警告。纯 Python、无重型原生依赖,装得快,跟
        # jsonschema/tqdm 一个量级,放进阻塞式核心依赖清单不会拖慢首启。
        # (OTLP 导出器额外依赖 grpcio,较重且默认不导出——按需手动装,见下方引导,
        # 不放进这里,呼应"语音依赖不阻塞首启"的同一条原则。)
        "opentelemetry.sdk": "opentelemetry-sdk",
    }
    # 高性能事件循环(平台各取所需):Windows 默认 Proactor 循环开销大(真机:
    # 面板首开并发把循环拖出 10s 级冻结),winloop ≈5×;Linux/macOS 用 uvloop。
    # 装不上/探针不过都自动退回默认循环(core/fast_loop.py),零风险。
    if os.name == "nt":
        core_modules["winloop"] = "winloop"
    else:
        core_modules["uvloop"] = "uvloop"
    for mod_name, pip_name in core_modules.items():
        try:
            __import__(mod_name)
        except Exception:
            core_deps_missing.append(pip_name)

    if not core_deps_missing:
        print_item("Python 核心依赖", "ok")
    else:
        print_item(f"缺失 {len(core_deps_missing)} 个包", "warn", f"{', '.join(core_deps_missing)}")
        print_item("正在自动安装...", "ok")
        if _run_pip_install(core_deps_missing):
            print_item(f"已安装 {len(core_deps_missing)} 个 Python 包", "ok")
        else:
            print_item("pip install 失败(默认源+国内镜像均不通)", "error")
            all_ok = False

    # 2.2 .env auto-create
    if not env_status.get("env_exists") and ENV_EXAMPLE.exists():
        print_item("从 .env.example 创建 .env...", "ok")
        try:
            shutil.copy(ENV_EXAMPLE, ENV_FILE)
            print_item(".env 已创建", "ok", "请编辑配置你的 API Key")
        except Exception as exc:
            print_item(f".env 创建失败: {exc}", "warn")

    # 2.3 Node.js + npm auto-install
    # PR-CROSS-PLATFORM: 优先检测系统是否已有 node/npm，避免重复安装
    if not env_status.get("npm_installed"):
        # 若用户已手动安装 Node.js（如 v24 等任意版本），直接复用
        if shutil.which("node") and shutil.which("npm"):
            node_ver = sp.run(["node", "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10).stdout.strip()
            print_item(f"检测到 Node.js {node_ver}，跳过自动安装", "ok")
            env_status["npm_installed"] = True
        else:
            print_item("Node.js + npm 未安装，正在自动安装...", "warn")
            node_installed = False
            # PR-CROSS-PLATFORM: 当前自动安装脚本仅支持 Linux
            if sys.platform != "linux":
                print_item(
                    f"当前平台 {sys.platform} 暂不支持自动安装 Node.js",
                    "warn",
                    "请手动下载安装: https://nodejs.org/ (推荐 v20 LTS)",
                )
            else:
                try:
                    import platform
                    machine = platform.machine().lower()
                    node_ver = "v20.11.0"
                    node_arch = "linux-arm64" if "arm" in machine or "aarch64" in machine else "linux-x64"
                    node_tar = f"node-{node_ver}-{node_arch}.tar.xz"
                    # 弱网加固:国内镜像优先候选 + 官方源兜底,进度条可见,
                    # 超时放宽(~25MB 在弱网 120s 不够,300s/候选)。
                    _node_urls = [
                        f"https://npmmirror.com/mirrors/node/{node_ver}/{node_tar}",
                        f"https://nodejs.org/dist/{node_ver}/{node_tar}",
                    ]
                    node_tmp = Path("/tmp") / node_tar
                    node_dest = Path.home() / ".local" / "node"

                    print_item(f"正在下载 Node.js {node_ver}...", "ok")
                    rc = 1
                    for _node_url in _node_urls:
                        rc = sp.run(
                            ["curl", "-fL", "--progress-bar", "--retry", "3",
                             "-o", str(node_tmp), _node_url],
                            timeout=300,
                        ).returncode
                        if rc == 0:
                            break
                        print_item("该源下载失败,轮换下一候选...", "warn", _node_url)
                    if rc == 0:
                        node_dest.parent.mkdir(parents=True, exist_ok=True)
                        rc2 = sp.run(
                            ["tar", "-xf", str(node_tmp), "-C", str(node_dest.parent), "--strip-components=1"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                        ).returncode
                        if rc2 == 0 or (node_dest.parent / "bin" / "node").exists():
                            bin_dir = node_dest.parent / "bin"
                            if bin_dir.exists():
                                os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
                                bashrc = Path.home() / ".bashrc"
                                path_line = f'export PATH="{bin_dir}:$PATH"'
                                if bashrc.exists():
                                    content = bashrc.read_text()
                                    if path_line not in content:
                                        bashrc.write_text(content + f"\n# Galaxy Node.js\n{path_line}\n")
                                node_installed = True
                                print_item(f"Node.js {node_ver} 已安装", "ok", str(bin_dir))
                except Exception as exc:
                    print_item(f"Node.js 自动安装失败: {exc}", "warn")
                if not node_installed:
                    print_item("Node.js 安装失败", "warn", "请手动安装: https://nodejs.org/")

    # 2.4 Electron / npm deps —— 正常下载 + 缺失/残缺自动补齐
    #   electron_deps_ok 现在是【完整性】判定(见 check_environment):
    #     - node_modules 不存在        → 全新正常下载(npm install)
    #     - node_modules 在但 cli.js 缺 → 残缺,同样跑 npm install 把缺的补齐
    #     - 完整                        → 跳过
    #   npm install 本身是幂等的:该下的下、已在的跳过,既是"正常下载"也是"补齐"。
    npm_cmd = shutil.which("npm")
    if npm_cmd and not env_status.get("electron_deps_ok"):
        _node_modules_exists = (ELECTRON_DIR / "node_modules").exists()
        if _node_modules_exists:
            print_item("检测到 Electron 依赖残缺，正在补齐...", "ok")
        else:
            print_item("正在下载 Electron 依赖...", "ok")

        # 弱网加固:①electron 二进制走国内镜像(避开 GitHub 卡死,与
        # electron/.npmrc 双保险),多候选镜像轮换抗单点/路径失效;
        # ②npm 网络重试/超时放宽;③【流式输出】不再 capture,让 npm 进度条
        # 可见——避免"看着像卡死"的错觉;④首次失败逐镜像回退再试。
        _npm_net_flags = [
            "--fetch-retries=5",
            "--fetch-retry-mintimeout=10000",
            "--fetch-retry-maxtimeout=120000",
            "--fetch-timeout=300000",
        ]
        # (electron 二进制镜像, 附加 npm registry 参数)候选,逐个尝试。
        _attempts = [
            ("https://npmmirror.com/mirrors/electron/", []),
            ("https://registry.npmmirror.com/-/binary/electron/",
             ["--registry=https://registry.npmmirror.com"]),
            ("", []),  # 最后回退官方源(直连 GitHub 良好的用户)
        ]

        def _run_npm_install(electron_mirror: str, extra: list) -> int:
            env = dict(os.environ)
            if electron_mirror:
                env["ELECTRON_MIRROR"] = electron_mirror
            try:
                # 流式输出(不 capture):慢网也能看到进度,不误判卡死。
                return sp.run(
                    [npm_cmd, "install", *_npm_net_flags, *extra],
                    cwd=str(ELECTRON_DIR),
                    env=env, timeout=900,
                ).returncode
            except Exception as exc:  # noqa: BLE001
                print_item(f"npm install 异常: {exc}", "warn")
                return 1

        rc = 1
        for _i, (_mirror, _extra) in enumerate(_attempts):
            if _i > 0:
                print_item(f"npm install 失败,切换镜像重试({_i}/{len(_attempts) - 1})...", "warn")
            rc = _run_npm_install(_mirror, _extra)
            if rc == 0:
                break
        if rc == 0:
            print_item("Electron 依赖就绪", "ok")
        else:
            print_item(
                "npm install 仍失败", "warn",
                "可手动: cd electron && npm install --registry=https://registry.npmmirror.com",
            )

    # 2.5 Ollama install hint + model auto-download
    if not env_status.get("ollama_installed"):
        print_item("Ollama 未安装", "warn", "curl -fsSL https://ollama.com/install.sh | sh")
        print_item("  或访问: https://ollama.com/download", "info")
    else:
        print_item("正在检查 Ollama 模型...", "ok")
        try:
            rc = sp.run(
                ["ollama", "list"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
            )
            if rc.returncode == 0 and rc.stdout.strip():
                models = [line.split()[0] for line in rc.stdout.strip().split("\n")[1:] if line.strip()]
                print_item(f"Ollama 模型: {len(models)} 个", "ok", ", ".join(models[:3]))
            else:
                # 按【实际硬件】挑推荐模型再拉，而不是写死 12B：无独显的笔记本只会拉轻量的
                # gemma4:e2b（不会白下 8GB 的大模型）。仅探测、不持久化，Phase 5 仍可改选。
                try:
                    from core import model_selection as _ms
                    rec_model = _ms.recommend()
                except Exception:
                    rec_model = "gemma4:e2b"
                print_item("未检测到本地模型，正在下载推荐模型...", "ok", rec_model)
                # 弱网加固:①流式输出让 ollama 自带进度条可见(此前 capture
                # 导致几 GB 的下载全程无声,"看着像卡死");②超时放宽到 1h——
                # 600s 在弱网下必然误杀大模型下载(ollama pull 本身断点续传,
                # 超时后重跑会从断点继续,但不该让正常慢速下载被误判失败)。
                try:
                    rc2 = sp.run(["ollama", "pull", rec_model], timeout=3600).returncode
                except sp.TimeoutExpired:
                    rc2 = -1
                    print_item("模型下载超 1h 未完成", "warn",
                               f"ollama pull {rec_model} 支持断点续传,重跑即从断点继续")
                if rc2 == 0:
                    print_item(f"模型 {rec_model} 下载完成", "ok")
                elif rc2 != -1:
                    print_item("模型下载失败", "warn", f"ollama pull {rec_model} 手动重试")
        except Exception as exc:
            print_item(f"Ollama 模型检查失败: {exc}", "warn")

    # 2.6 Voice dependencies (REQUIRED)
    print_item("检查语音依赖...", "ok")
    # sounddevice 是"对它说话它就回应"这条主路径(VoiceLoop→麦克风采集)的关键依赖,
    # 之前这份清单漏了它 → 明明麦克风采集打不开,横幅却报"语音依赖 ✓",误导排查。
    # 注:import sounddevice 会一并加载 PortAudio 原生库,故它失败也能兜住"PortAudio 缺失"。
    voice_deps = {
        "sounddevice": "sounddevice",
        "pvporcupine": "pvporcupine",
        "webrtcvad": "webrtcvad",
        "faster_whisper": "faster-whisper",
    }
    voice_missing = []
    for mod_name, pip_name in voice_deps.items():
        try:
            __import__(mod_name)
        except Exception:
            voice_missing.append(pip_name)

    if not voice_missing:
        print_item("语音依赖", "ok", "sounddevice, pvporcupine, webrtcvad, faster-whisper")
    else:
        # 首启健壮:【不】在启动时现装语音依赖 —— pip 安装慢(_run_pip_install 超时 900s,
        # faster-whisper 会拉几百 MB),且依赖网络/镜像,一旦卡住/失败就把首启拖死或拖挂。
        # 语音是【可选】的麦克风路径(缺了远程/文字路径照常可用),故改为清晰引导按需手动装。
        print_item(f"语音依赖缺失(可选,麦克风路径用): {', '.join(voice_missing)}", "warn")
        print_item("按需手动安装(不自动装以免拖慢/挂死首启)", "warn",
                   f"pip install {' '.join(voice_missing)}  —— 或 `python main.py setup`")

    # pyaudio (needs system libs;同样不在首启现装)
    try:
        __import__("pyaudio")
        print_item("PyAudio", "ok")
    except Exception:
        print_item("PyAudio 未安装(可选)", "warn",
                   "手动: apt install portaudio19-dev && pip install pyaudio")

    # OTLP 导出器(可选;真正导出追踪数据到 Jaeger/Tempo 等后端时才需要,依赖较重
    # 的 grpcio,默认 GALAXY_OTEL_EXPORTER 未设时用不上——不在首启阻塞安装,
    # 同一条"首启健壮"原则,按需手动装)
    try:
        __import__("opentelemetry.exporter.otlp.proto.grpc.trace_exporter")
    except Exception:
        print_item(
            "OTLP 追踪导出器未安装(可选,导出到 Jaeger/Tempo 等才需要)",
            "warn",
            "手动: pip install opentelemetry-exporter-otlp-proto-grpc",
        )

    return all_ok


def _run_setup_wizard() -> int:
    """Run the interactive setup wizard."""
    wizard_path = PROJECT_ROOT / "setup_wizard.py"
    if wizard_path.exists():
        sys.exit(subprocess.call([sys.executable, str(wizard_path)]))
    else:
        logger.info("Configuration wizard not found: %s", wizard_path)  # L2 fixed
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------

def _apply_model_cli_args(args) -> None:
    """把 --model / --select-model 应用到环境变量；真正的主脑选择移到 Phase 5「AI 大脑」进行
    （不在开头打断）。--select-model 清除已保存选择以触发重新选择。"""
    try:
        if getattr(args, "model", None):
            os.environ["OLLAMA_MODEL"] = args.model
        if getattr(args, "select_model", False):
            # 清除已保存选择以触发重新选择。主脑现收敛在 model_catalog 的统一记录
            # (runtime/model_state.json);连旧的 .galaxy_model 一并清掉(迁移期兼容)。
            for _p in (PROJECT_ROOT / "runtime" / "model_state.json",
                       PROJECT_ROOT / ".galaxy_model"):
                try:
                    _p.unlink()
                except Exception:
                    pass
            os.environ.pop("OLLAMA_MODEL", None)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Galaxy V2 Unified Entry")
    parser.add_argument("--setup", action="store_true", help="Run interactive setup wizard")
    # Accept --host/--port so the documented start command
    # (`python main.py --host 127.0.0.1 --port 9000`) works instead of crashing
    # with "unrecognized arguments".  Default None ⇒ keep the config default.
    parser.add_argument("--host", type=str, default=None, help="API 服务监听地址 (默认取配置)")
    parser.add_argument("--port", "-p", type=int, default=None, help="API 服务端口 (默认 9000)")
    parser.add_argument("--model", type=str, default=None,
                        help="指定本地主脑模型 tag（跳过交互选择，如 gemma4:12b / openbmb/minicpm-o4.5）")
    parser.add_argument("--select-model", action="store_true",
                        help="强制重新选择 AI 主脑模型（清除已保存选择）")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="详细模式：展开每个启动阶段的逐项明细（默认折叠成一行）")
    parser.add_argument("--autostart", action="store_true",
                        help="(Windows) 注册开机自启：开机/被 WOL 盒子唤醒后自动拉起 Galaxy + 托盘")
    parser.add_argument("--autostart-remove", action="store_true",
                        help="(Windows) 取消开机自启")
    args = parser.parse_args()

    # -v 同时落到环境变量：子模块（unified_launcher 等）无需逐层透传即可读到。
    if args.verbose:
        os.environ["GALAXY_VERBOSE"] = "1"

    # 开机自启一键设置：让电脑(被 WOL 盒子)开机进系统后自动拉起整套 Galaxy + 托盘，
    # 配合 entrypoint.json 写出的 Tailscale/LAN 地址，三端无需手填 IP 即可发现网关秒连。
    if args.autostart or args.autostart_remove:
        try:
            from windows_service import autostart as _as
            if args.autostart_remove:
                print_item(f"取消开机自启: {_as.unregister_all()}", "ok")
            else:
                print_item(f"已注册开机自启: {_as.register_all(tray_mode=True)}", "ok")
                print_item("下次开机（或被 WOL 盒子唤醒）将自动启动 Galaxy", "info")
        except Exception as _exc:  # noqa: BLE001
            print_item(f"开机自启设置失败: {_exc}", "error")
            return 1
        return 0

    if args.setup:
        _run_setup_wizard()
        return 0

    # ── PR-01: entrypoint role contract enforcement ──────
    if not assert_single_unique_main_entrypoint():
        print_item("入口角色契约校验失败: 唯一主入口必须是 main.py", "error")
        return 1
    if not ensure_entrypoint_role(MAIN_ENTRY_ID, EntrypointRole.UNIQUE_MAIN):
        print_item("入口角色契约校验失败: MAIN_ENTRY_ID 必须为 UNIQUE_MAIN", "error")
        return 1
    launcher_path = PROJECT_ROOT / "unified_launcher.py"
    if not launcher_path.exists():
        print_item(f"子入口缺失: {launcher_path}", "error")
        return 1

    # ── Phase 0: Galaxy Banner ───────────────────────────
    print_banner()

    # 仅应用 --model/--select-model 到环境；真正的主脑模型选择在 Phase 5「AI 大脑」进行
    # （不在开头打断用户）。
    _apply_model_cli_args(args)

    # 启动每阶段计时(隐蔽:只进 logs/lumiv.log + 面板诊断;GALAXY_PHASE_TIMING=0 可关)
    try:
        from core.startup_timing import phase as _phase_timer
    except Exception:  # noqa: BLE001
        from contextlib import contextmanager as _cm

        @_cm
        def _phase_timer(_name):  # 兜底:计时模块缺失也不影响启动
            yield

    # ── Phase 0: Environment check ───────────────────────
    print_phase("[Phase 0] 环境检查")
    with _phase_timer("Phase 0 环境检查"):
        env_status = phase0_env_check()

    # ── Phase 1: System pre-flight (original 7-phase) ───
    print_phase("[Phase 1] 系统预检")
    with _phase_timer("Phase 1 系统预检"):
        ready = _run_orchestrator_preflight()
    if not ready:
        print_item("系统预检未通过，请先修复上述问题", "error")
        return 1

    # ── Phase 2: Ensure dependencies ─────────────────────
    print_phase("[Phase 2] 依赖确保")
    with _phase_timer("Phase 2 依赖确保"):
        phase2_ensure_deps(env_status)

    # ── Start unified launcher (DIRECT CALL, not subprocess)
    print_phase("[系统启动]")
    print_item("正在启动 Galaxy 后端服务...", "ok")

    from unified_launcher import GalaxyUnified

    lumiv = GalaxyUnified()
    lumiv._verbose = bool(args.verbose)
    # Apply optional CLI overrides for the API gateway bind address/port.
    if args.host:
        lumiv.config.host = args.host
    if args.port:
        lumiv.config.web_ui_port = args.port

    async def _run() -> None:
        # ── Galaxy WebSocket Bridge — 桌面覆盖层事件推送 ──
        try:
            from core.lumiv_websocket_bridge import GalaxyPresenceBridge
            _ws_bridge = GalaxyPresenceBridge.get_instance()
            asyncio.create_task(_ws_bridge.start())
        except Exception as _exc:
            logger.debug("GalaxyWebSocketBridge init skipped (non-fatal): %s", _exc)
        await lumiv.start()

    # 高性能事件循环(Windows: winloop ≈5×默认 Proactor;Linux/macOS: uvloop)。
    # 必须在 asyncio.run 之前装策略;内置子进程探针,失败自动还原默认(宁慢勿哑)。
    try:
        from core.fast_loop import install_fast_loop
        install_fast_loop()
    except Exception:
        pass  # 缺包/异常都走默认循环,零影响

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print()
        print_phase("[系统停止]")
        print_item("正在优雅关闭所有服务...", "ok")
        lumiv.stop()
        print_item("所有服务已停止", "ok")

    return 0


if __name__ == "__main__":
    main()
