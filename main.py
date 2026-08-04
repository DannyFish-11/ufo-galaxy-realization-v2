#!/usr/bin/env python3
# PR-WIN-ENCODING: Force UTF-8 on Windows to prevent UnicodeEncodeError in logs
import os
import sys

# ── .env 加载:必须在任何读取 os.environ 的代码之前完成 ──────────────────
# python-dotenv 早就在 requirements 里锁了版本,但全仓库范围内从未被真正调用
# 过——.env 文件从来没有被加载进 os.environ。真机复现过:「模型」tab 存的任何
# API Key(不止 DeepSeek，OpenAI/Anthropic/Gemini/Groq/... 全部受影响)在保存
# 当次生效(setConfig 会同步写 os.environ),但重启新进程后——凡是代码直接读
# os.environ(而不是全部经过 core.unified_config 的间接路径)——统统读不到，
# 表现为"存了，重启后又没了"。这里在进程最早期加载 .env，且 override=False
# (不覆盖已存在的真实 shell/系统环境变量，尊重用户显式导出的优先级更高)。


def load_env_files_into_environ(root: str = "") -> None:
    """把 runtime/secrets.env 与 .env 的【非空、非毒值】键注入 os.environ。

    只在 main.py **作为脚本运行**时调用(见下方 ``__name__`` 守卫),不在
    ``import main`` 时执行 —— 这是刻意的:

    进程级 ``os.environ`` 是全局可变状态。一旦"import 这个模块"本身就带来
    全局副作用,任何 ``import main`` 的地方(测试里有 4 处只为读一个常量)
    都会把开发者本机 .env 里的真实值灌满整个进程,并且**再也退不回去**
    ——后续所有代码看到的都是被污染的环境。实测后果:跟着 INSTALL.md 走完
    (bootstrap 会生成 .env)再跑 pytest,会多出 8 条与本次改动毫无关系的
    失败(MEMORY_DB_PATH 指向容器路径导致建库失败 2 条;各家 API_KEY 凭空
    出现导致"缺 key 时不应入候选池"类断言失败 6 条),且顺序依赖、难复现。
    CI 上没有 .env 所以永远看不到 —— 只砸本机开发者。

    加载纪律(三条,都是真机复现过的坑,不能放松):
    1. **只加载非空值**。设置面板自动生成的 .env 会把【全部】schema 键写成
       ``KEY=``(空值)。空字符串一旦进 os.environ 就会顶掉代码默认值:
       ``os.environ.get("OLLAMA_URL", "http://localhost:11434")`` 在
       ``OLLAMA_URL=""`` 存在时返回 ``""`` 而不是默认值。真机症状一整串都源于
       此 —— LocalBrainManager 拿空 URL ping Ollama(报 "Request URL is missing
       an 'http://' or 'https://' protocol"、Ollama 明明在跑却判"服务未响应/
       模型未就绪")、Redis "must specify scheme"、NATS "invalid hostname"。
       所以这里不能用 ``load_dotenv()`` 整个灌进去。
    2. **值以 # 开头一律视同未配置**。python-dotenv 会把「KEY=   # 注释」这种
       【空值 + 行内注释】整段注释当成值(实测 1.2.2:``OLLAMA_URL= # e.g.
       http://...`` → ``'# e.g. http://...'``),经 normalize 补协议头后变成
       ``http://#...`` 的怪 URL,骗过全部 startswith 检查。合法配置值不可能
       以 # 开头。
    3. **不覆盖已存在的键**。shell/系统显式导出的优先级最高;secrets.env 先于
       .env 加载(面板保存的最新真值先到先得)。

    密钥库(runtime/secrets.env)必须一起加载:设置面板把 API Key 这类 secret
    写进它而非 .env(见 core/config_store.py),此前重启后无人把它注回
    os.environ —— 直读 os.getenv 的路径(含面板"已配置"角标)统统看不到,
    表现为"Key 存了,重启后又显示未配置"。

    ``root`` 只为测试留的注入点(默认= main.py 所在目录,即仓库根)。生产路径
    永远用默认值 —— 没有它就只能靠"在仓库根真造一个 .env"来验证这三条纪律,
    那会踩到开发者自己的 .env。
    """
    try:
        from dotenv import dotenv_values

        _root = root or os.path.dirname(os.path.abspath(__file__))
        for _rel in ("runtime/secrets.env", ".env"):
            for _k, _v in (dotenv_values(os.path.join(_root, _rel)) or {}).items():
                if _v and not _v.lstrip().startswith("#") and _k not in os.environ:
                    os.environ[_k] = _v
    except Exception:
        pass


# 调用点见下方「进程级配置的唯一调用点」—— 与 Windows 控制台、HF 端点合在
# 一个 __main__ 守卫里,仍在其余 import 之前。

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


def configure_windows_console() -> None:
    """Windows 控制台 UTF-8 + 进程优先级。

    与 .env 加载同理,只在**作为脚本运行**时调用:被 import 时重写调用方的
    sys.stdout/sys.stderr、抬高整个进程的调度优先级,都是越权行为。
    """
    if sys.platform != "win32":
        return
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


def configure_huggingface_endpoint() -> None:
    """把 HF 端点指向国内镜像,并把超时/重试压到最小。

    **必须在任何 HF 库(transformers/sentence_transformers/huggingface_hub/
    faster_whisper)被 import 之前设置**,否则 HF_ENDPOINT 被库缓存、镜像不生效
    → 退回 huggingface.co,在国内被墙 → 每个文件 5 次重试 × 指数退避 → 嵌入器/
    Whisper 加载能卡 4 分钟,把 /chat/stream 拖到 270s(实测)。所以调用点仍在
    本文件最顶端、其余 import 之前 —— 只是加了 ``__main__`` 守卫。

    守卫的理由与 .env 那处相同:``import main`` 不该把**整个进程**的 HuggingFace
    端点悄悄改掉。测试进程里尤其不该 —— 一次无关的 import 就让后续所有用例对着
    一个镜像站解析下载地址,而且退不回去。

    可用 GALAXY_HF_MIRROR=0 关闭镜像。
    """
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


# ── 进程级配置的唯一调用点 ────────────────────────────────────────────────
# 三件事都必须发生在其余 import 之前(.env 要早于任何读 os.environ 的代码,
# HF 端点要早于任何 HF 库),所以调用点只能待在文件顶端。守卫保证它们只在
# `python main.py` 时发生 —— `import main` 不产生任何全局副作用。
if __name__ == "__main__":
    load_env_files_into_environ()
    configure_windows_console()
    configure_huggingface_endpoint()

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

import argparse
import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

from core.ascii_art import (
    GALAXY_TAGLINE,
    GALAXY_VERSION,
    print_banner,
    print_section_header,
)

# ── Phase output helpers ──────────────────────────────────
_PHASE_WIDTH = 60


def print_phase(title: str) -> None:
    """打印阶段小标题。

    统一走 core.cli_render（与启动后半段同一套 clig.dev 风格：细线 + 干净标题，
    而非旧的 ═══×60 大框）——让【整个克隆界面】前后一致。cli_render 不可用时兜底回旧风格。
    """
    # 阶段切换时把「当前栏目」定下来，后续 print_item 的记录自动落到对的栏目。
    # 这样 71 个 print_item 调用点一个都不用改，栏目归属仍然准确。
    try:
        from launcher import ui as _ui

        _ui.set_column(_ui.column_for_title(title))
    except Exception:  # noqa: BLE001 — 记录层不可用绝不能挡启动
        pass
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
    # 唯一咽喉：交给 launcher.ui.step —— 它同时【记一笔结构化事实】和【打这一行】。
    #
    # 输出逐字节不变：ui.step 内部还是走 cli_render.phase，用的是同一组几何常量
    # (CONTENT_INDENT/ICON_COL/LABEL_COL)。变的是每一项现在都留下了痕迹，最终
    # 落到 runtime/startup.json —— 启动失败时可以直接把那个文件发出来，而不是
    # 截一张彩色终端的图让人猜。
    #
    # 用 phase()(2 格缩进,标签第 4 列)而非 detail()(6 格缩进)——让 Phase 0/1/2
    # 的状态项与「系统启动」后的运行时项(核心服务/基础设施/... 也走 phase)以及
    # ▶ 启动行处在【同一列】。此前 Phase 段 6 格、运行时段 2 格,对勾对不齐。
    printed = False
    try:
        from launcher import ui as _ui

        _ui.step(name, status, detail)
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
    MAIN_ENTRY_ID,
    EntrypointRole,
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
        str(log_dir / "lumiv.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
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
    # 修 logging 双写(所有者 Windows 真机日志:HF 下载重试等每条日志打印两遍)。
    # 根因:huggingface_hub 在 import 时给自己的库根 logger("huggingface_hub")
    # 挂了一个裸 StreamHandler,却不关 propagate —— 同一条 WARNING 先经它自己的
    # handler 打一遍,再冒泡到根 logger 的控制台 handler 又打一遍(双 handler)。
    # 这里预先关掉其向根 logger 的冒泡(它自带的 handler 仍保证控制台可见一次),
    # 并补挂本文件 handler,让这些日志照旧落进 logs/lumiv.log 不丢证据。
    _hf_logger = logging.getLogger("huggingface_hub")
    _hf_logger.propagate = False
    _hf_logger.addHandler(handler)
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

SYSTEM_ORCHESTRATOR_AUTHORITY: str = "main.py:SYSTEM_ORCHESTRATOR — canonical staged bring-up contract (PR-2)"


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


#: :class:`launcher.record.Status` → ``print_item`` 的老状态词汇。
#: 只在 ``launcher.ui`` 不可用的兜底路径上用到（正常路径直接传 Status）。
_STEP_STATUS_TO_LEGACY = {"ok": "ok", "degraded": "warn", "failed": "error", "skipped": "info"}


def phase0_env_check() -> dict:
    """Phase 0: 环境检查 —— 判据全部来自 :mod:`launcher.env_check`。

    这里原本自带一整套探测（Python / pip / .env / API Key / npm / Node /
    Electron / Ollama），而 ``launch_desktop.py`` 另有一套自称"精简版"的
    ``phase0_environment_check``。两份**互不知情**，同一个问题会给出不同答案：

    - pip：这边用 ``which("pip")``（可能是别的解释器的 pip），那边用
      ``sys.executable -m pip``（问的才是"我这个 Python 能不能装包"）；
    - Electron：这边用 ``electron_package_intact``（识别残缺安装），那边只看
      ``node_modules/electron`` 目录在不在；
    - API Key：这边读 ``.env`` + ``runtime/secrets.env``（面板保存后密钥收敛到
      后者），那边只读 ``os.environ`` —— 密钥存对了也一直报"未配置"；
    - Ollama：这边只查装没装，那边还查在不在跑、有哪些模型。

    合并后逐行取更强的那个判据，每一条都有测试钉住（见
    ``tests/test_launcher_env_check.py``）。本函数现在只做两件事：**要一份事实**，
    **把它交给唯一的输出咽喉打出来**。

    Returns:
        与合并前**键相同**的 status dict（键取两个老调用方的并集），
        且仍然可变 —— ``phase2_ensure_deps`` 会在自愈成功后回写。
    """
    from launcher import env_check as _env_check

    # 路径由本文件给：ENV_FILE / ELECTRON_DIR 的所有权留在入口，
    # 检查器不再自己持一份同名常量（也让这两个路径保持可注入）。
    report = _env_check.check_environment(env_file=ENV_FILE, electron_dir=ELECTRON_DIR)
    for step in report.to_steps():
        # 优先走 _ui.step 而不是 print_item：事实已经是 StepResult 了，再翻译成
        # ("ok"/"warn", 文本) 又翻回来只会丢掉 hint 与 detail。
        # 兜底与 print_item 同款（本文件其余 71 处的既有约定）：ui 不可用时也要
        # 有一行能看的输出，环境检查的结论正是最不该在这种时候消失的东西。
        try:
            from launcher import ui as _ui

            _ui.step(
                step.name,
                step.status,
                step.value,
                column=step.column,
                hint=step.hint,
                **step.detail,
            )
        except Exception:
            print_item(step.name, _STEP_STATUS_TO_LEGACY.get(step.status.value, "info"), step.value)
    return report.to_status_dict()


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

    # 弱网加固交给 launcher.deps —— 镜像轮换/重试/流式输出只写一份。
    #
    # 此前这套逻辑在本文件里是内嵌的局部函数,而 install.py / install_windows.ps1
    # 【一个镜像都没有】、install.sh 只有一个。同一件事四份实现、四种抗弱网强度,
    # 谁也不知道别人有什么。搬进 launcher/deps.py 之后:
    #   · 候选表只有一份(默认源 → 清华 → 阿里云),且认 GALAXY_PIP_INDEX 覆盖
    #     (沿用 install.sh 已有的约定);
    #   · 顺带补上 --trusted-host(install.sh 有、这边原来没有,某些企业网下
    #     镜像证书链不受信时会卡在这一步);
    #   · 结果是 InstallResult 而不是裸 bool,能说清"用哪个源成功的/试了几次"。
    from launcher import deps as _deps

    def _run_pip_install(pkgs: list, timeout: int = 900) -> bool:
        """逐镜像候选安装 pkgs,全部失败才返回 False(诚实上报)。"""
        result = _deps.pip_install(pkgs, timeout=timeout)
        if result.ok:
            if result.attempts > 1:
                print_item("经镜像回退后安装成功", "warn", result.index_used or "默认源")
            return True
        print_item(f"pip 安装失败(试了 {result.attempts} 个源)", "warn", result.stderr_tail[:120])
        return False

    # 2.0 Ensure pip is available
    if not env_status.get("pip_ok"):
        print_item("pip 未安装，正在修复...", "warn")
        pip_fixed = False
        # Method 1: ensurepip
        try:
            rc = sp.run(
                [sys.executable, "-m", "ensurepip", "--upgrade"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
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
                rc = sp.run(
                    [
                        sys.executable,
                        "-c",
                        f"import urllib.request; "
                        f"urllib.request.urlretrieve('https://bootstrap.pypa.io/get-pip.py', r'{get_pip_tmp}')",
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                ).returncode
                if rc == 0:
                    rc2 = sp.run(
                        [sys.executable, get_pip_tmp],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=60,
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
    # 清单搬到 launcher/deps.py:CORE_MODULES —— "这个项目启动需要什么"此前只存在
    # 于本函数体里,三个 installer 谁也不知道它(它们各自去装 requirements*.txt,
    # 与这份精选清单没有任何交叉校验)。平台相关的事件循环由 platform_core_modules()
    # 追加(Windows→winloop / 其余→uvloop),判据与理由都在那边写着。
    core_modules = _deps.platform_core_modules()
    core_deps_missing = _deps.probe_missing(core_modules)

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
            node_ver = sp.run(
                ["node", "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10
            ).stdout.strip()
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
                            ["curl", "-fL", "--progress-bar", "--retry", "3", "-o", str(node_tmp), _node_url],
                            timeout=300,
                        ).returncode
                        if rc == 0:
                            break
                        print_item("该源下载失败,轮换下一候选...", "warn", _node_url)
                    if rc == 0:
                        node_dest.parent.mkdir(parents=True, exist_ok=True)
                        rc2 = sp.run(
                            ["tar", "-xf", str(node_tmp), "-C", str(node_dest.parent), "--strip-components=1"],
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            timeout=30,
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
    # env_status 是 Phase 0 拍的快照,而 Phase 1 的编排器 Phase 6(DESKTOP_SURFACE)
    # 就在 Phase 0 和这里【中间】跑过一次 npm install。照着两个阶段前的旧快照判断,
    # 依赖明明已经装好了也会再整装一遍(实测重复消耗 ~20s 纯等待,且这段是阻塞在
    # 网关 bind 之前的)。完整性判定只是几次 os.path.isfile,重新取一次实时状态的
    # 代价可忽略;失败路径完全不变——Phase 6 装失败/被跳过时这里照样判 False 并
    # 跑下面那套三镜像重试(比 Phase 6 的更抗弱网),补齐能力一点没少。
    if npm_cmd and not env_status.get("electron_deps_ok"):
        try:
            from core.electron_launch_guard import electron_package_intact

            if electron_package_intact(str(ELECTRON_DIR)):
                env_status["electron_deps_ok"] = True
                print_item("Electron 依赖已就绪(启动早期阶段已装好)", "ok")
        except Exception:  # noqa: BLE001
            pass  # 复检本身出错 → 保持原判断,照常走安装
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
        # 弱网加固交给 launcher.deps.npm_install:electron 二进制走国内镜像候选
        # 轮换(避开 GitHub 卡死,与 electron/.npmrc 双保险)、npm 网络重试放宽、
        # 【流式输出】不 capture 让进度条可见(避免"看着像卡死")、失败逐镜像回退。
        # 这一整套此前只在本文件里有,launch_desktop 的 npm install 一条都没有。
        _npm_result = _deps.npm_install(ELECTRON_DIR, npm_path=npm_cmd)
        rc = 0 if _npm_result.ok else 1
        if _npm_result.ok and _npm_result.attempts > 1:
            print_item(
                f"npm install 经镜像回退后成功({_npm_result.attempts} 次)", "warn", _npm_result.index_used or "官方源"
            )
        if rc == 0:
            print_item("Electron 依赖就绪", "ok")
        else:
            print_item(
                "npm install 仍失败",
                "warn",
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
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            if rc.returncode == 0 and rc.stdout.strip():
                models = [line.split()[0] for line in rc.stdout.strip().split("\n")[1:] if line.strip()]
                print_item(f"Ollama 模型: {len(models)} 个", "ok", ", ".join(models[:3]))
            else:
                # 这里【只报告、不下载】。模型拉取由 Phase 5「AI 大脑」统一负责
                # (unified_launcher._phase5 → core.model_selection.background_pull),
                # 那条路径在每个维度上都严格更优,曾经放在这里的阻塞式 ollama pull
                # 属于纯粹重复且更差的一份:
                #   · 拉的模型不对——这里拉 recommend() 的硬件推荐值,而 Phase 5 拉
                #     resolve_main_brain() 的【用户实际选定】值;两者不同时,用户要
                #     先等一个自己根本不用的模型下完。
                #   · 阻塞网关——timeout=3600 且位于 bind 之前,首启机器上网关最长
                #     一小时不监听,用户连「保存 API Key」都做不了(真机反馈过的
                #     "后端未启动"就是这一类)。Phase 5 走后台线程,不挡启动。
                #   · 时序更早、更容易空放一枪——Phase 5 特意把 start_local_brain()
                #     排在拉取之前以确保 Ollama 真已就绪(见其 docstring 记录的竞态),
                #     而这里比它还早,ollama serve 往往尚未绑定端口。
                #   · 缺少 Phase 5 已有的 /api/show 残缺 manifest 核实、HuggingFace
                #     回退、版本不兼容诊断。
                print_item("未检测到本地模型", "warn", "将由 Phase 5「AI 大脑」按所选主脑后台拉取(不阻塞启动)")
        except Exception as exc:
            print_item(f"Ollama 模型检查失败: {exc}", "warn")

    # 2.6 Voice dependencies (REQUIRED)
    print_item("检查语音依赖...", "ok")
    # sounddevice 是"对它说话它就回应"这条主路径(VoiceLoop→麦克风采集)的关键依赖,
    # 之前这份清单漏了它 → 明明麦克风采集打不开,横幅却报"语音依赖 ✓",误导排查。
    # 注:import sounddevice 会一并加载 PortAudio 原生库,故它失败也能兜住"PortAudio 缺失"。
    voice_missing = _deps.probe_missing(_deps.VOICE_MODULES)

    if not voice_missing:
        print_item("语音依赖", "ok", "sounddevice, pvporcupine, webrtcvad, faster-whisper")
    else:
        # 首启健壮:【不】在启动时现装语音依赖 —— pip 安装慢(_run_pip_install 超时 900s,
        # faster-whisper 会拉几百 MB),且依赖网络/镜像,一旦卡住/失败就把首启拖死或拖挂。
        # 语音是【可选】的麦克风路径(缺了远程/文字路径照常可用),故改为清晰引导按需手动装。
        print_item(f"语音依赖缺失(可选,麦克风路径用): {', '.join(voice_missing)}", "warn")
        print_item(
            "按需手动安装(不自动装以免拖慢/挂死首启)",
            "warn",
            f"pip install {' '.join(voice_missing)}  —— 或 `python main.py setup`",
        )

    # pyaudio (needs system libs;同样不在首启现装)
    try:
        __import__("pyaudio")
        print_item("PyAudio", "ok")
    except Exception:
        print_item("PyAudio 未安装(可选)", "warn", "手动: apt install portaudio19-dev && pip install pyaudio")

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
    """Run the interactive setup wizard.

    真 bug 修复:此前不带任何参数调用 setup_wizard.py,而它的 main() 在没有
    --interactive/--quick/--test 时默认落到 quick_setup()(纯非交互、只从环境变量
    探测 API Key,探测不到就打印一行提示直接退出)——也就是说 start.bat 首启(无 .env
    时自动跑 `python main.py --setup`)实际上【什么交互向导都没跑】,包括数据库/
    容器运行时(Docker/Podman)配置在内的整个 run_interactive_setup() 流程全被跳过。
    这正是"克隆界面里没有 Docker/Podman 选择"的根因——不是选项没做,是这条路径
    压根没跑到有选项的那个函数。显式传 --interactive 走真正的交互向导。
    """
    wizard_path = PROJECT_ROOT / "setup_wizard.py"
    if wizard_path.exists():
        sys.exit(subprocess.call([sys.executable, str(wizard_path), "--interactive"]))
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
            for _p in (PROJECT_ROOT / "runtime" / "model_state.json", PROJECT_ROOT / ".galaxy_model"):
                try:
                    _p.unlink()
                except Exception:
                    pass
            os.environ.pop("OLLAMA_MODEL", None)
    except Exception:  # noqa: BLE001
        pass


def _record_module():
    """惰性取 launcher.record（退出码常量的唯一来源）。"""
    from launcher import record

    return record


def _run_nodes_command(args) -> int:
    """``python main.py nodes <start|stop|status|monitor|report>``。"""
    import asyncio as _asyncio

    from launcher import nodes as _nodes

    try:
        return _asyncio.run(_nodes.run_command(args.node_command, group=args.group, interval=args.interval))
    except KeyboardInterrupt:
        return _record_module().EXIT_INTERRUPTED
    except ValueError as exc:
        print_item(str(exc), "error")
        return _record_module().EXIT_USAGE


def _run_install_command(args) -> int:
    """``python main.py install [--core|--enhance|--all]``。

    只装依赖然后退出，不拉起系统。装什么、怎么装全部问
    :mod:`launcher.deps` —— 与启动期自愈**共用同一份**镜像轮换与依赖清单，
    所以不会再出现"``install.py`` 没有镜像回退、``main.py`` 有三个"那种漂移。
    """
    from launcher import deps as _deps
    from launcher import record as _record

    _ui_ok = True
    try:
        from launcher import ui as _ui

        _ui.begin(GALAXY_VERSION)
    except Exception:  # noqa: BLE001
        _ui_ok = False

    print_phase("[依赖安装]")
    is_win = os.name == "nt"
    want_enhance = args.all or args.enhance
    want_windows = args.all and is_win
    if args.core:
        want_enhance = want_windows = False

    plan: list = [("core", "核心依赖")]
    if want_enhance:
        plan.append(("enhance", "增强依赖"))
    if want_windows:
        plan.append(("windows", "Windows 依赖"))

    print_item("pip 源候选", "ok", f"{len(_deps.pip_index_candidates())} 个（GALAXY_PIP_INDEX 可覆盖）")
    all_ok = True
    for tier, label in plan:
        result = _deps.install_requirements(tier)
        if result.skipped_reason:
            print_item(label, "info", f"跳过：{result.skipped_reason}")
        elif result.ok:
            print_item(label, "ok", result.index_used or "默认源")
        else:
            print_item(label, "error", f"试了 {result.attempts} 个源都失败")
            if result.stderr_tail:
                print_item("  最后的报错", "warn", result.stderr_tail.strip()[:160])
            all_ok = False

    exit_code = _record.EXIT_OK if all_ok else _record.EXIT_DEPENDENCY
    if _ui_ok:
        try:
            from launcher import ui as _ui

            _ui.finish(exit_code, verbose=bool(os.environ.get("GALAXY_VERBOSE")), tui=False)
        except Exception:  # noqa: BLE001
            pass
    return exit_code


def main() -> int:
    # nodes 子命令的取值表要在 argparse 建表时就拿到。launcher.nodes 只含常量,
    # 真正会读配置的 system_manager 由它内部惰性加载 —— 所以这个 import 不会
    # 把节点表的读取拉进"只想 --version"的路径。
    try:
        from launcher import nodes as _launcher_nodes
    except Exception:  # noqa: BLE001
        _launcher_nodes = None

    parser = argparse.ArgumentParser(description="Galaxy V2 Unified Entry")
    # --version：CLI 该知道自己的版本。此前 GALAXY_VERSION 只印在横幅里，
    # 脚本/排障想拿版本号只能去 grep 源码或截横幅。
    parser.add_argument(
        "--version",
        action="version",
        version=f"Galaxy {GALAXY_VERSION} — {GALAXY_TAGLINE}",
        help="打印版本号后退出",
    )
    parser.add_argument("--setup", action="store_true", help="Run interactive setup wizard")
    # Accept --host/--port so the documented start command
    # (`python main.py --host 127.0.0.1 --port 9000`) works instead of crashing
    # with "unrecognized arguments".  Default None ⇒ keep the config default.
    parser.add_argument("--host", type=str, default=None, help="API 服务监听地址 (默认取配置)")
    parser.add_argument("--port", "-p", type=int, default=None, help="API 服务端口 (默认 9000)")
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="指定本地主脑模型 tag（跳过交互选择，如 gemma4:12b / openbmb/minicpm-o4.5）",
    )
    parser.add_argument("--select-model", action="store_true", help="强制重新选择 AI 主脑模型（清除已保存选择）")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="详细模式：展开每个启动阶段的逐项明细（默认折叠成一行）"
    )
    parser.add_argument(
        "--autostart", action="store_true", help="(Windows) 注册开机自启：开机/被 WOL 盒子唤醒后自动拉起 Galaxy + 托盘"
    )
    parser.add_argument("--autostart-remove", action="store_true", help="(Windows) 取消开机自启")
    # 子命令走**可选位置参数**而不是 argparse 的 subparsers。
    #
    # 理由是兼容性：现有的全部调用形态都是纯 flag（`python main.py --host ... --port ...`，
    # start.bat / start.sh / 文档 / 三端说明全是这么写的）。改成 subparsers 会让
    # "不带子命令"变成一种需要显式处理的特例，稍不留神就把最常用的那条路径打断。
    # 可选位置参数则是纯增量：不给就是原来的"启动整套系统"。
    parser.add_argument(
        "command",
        nargs="?",
        default=None,
        choices=["install", "nodes"],
        help=(
            "子命令。install = 只装依赖后退出（替代已无调用方的 python install.py）；"
            "nodes = 节点生命周期（替代 python system_manager.py）"
        ),
    )
    parser.add_argument(
        "node_command",
        nargs="?",
        default=None,
        choices=list(_launcher_nodes.NODE_COMMANDS) if _launcher_nodes else None,
        help="(nodes) start | stop | status | monitor | report",
    )
    parser.add_argument(
        "--group",
        "-g",
        default=_launcher_nodes.DEFAULT_GROUP if _launcher_nodes else "all",
        choices=list(_launcher_nodes.NODE_GROUPS) if _launcher_nodes else None,
        help="(nodes start) 节点组",
    )
    parser.add_argument(
        "--interval",
        "-i",
        type=int,
        default=_launcher_nodes.DEFAULT_INTERVAL if _launcher_nodes else 30,
        help="(nodes monitor) 监控间隔（秒）",
    )
    parser.add_argument("--all", action="store_true", help="(install) 核心 + 增强 + Windows 全装")
    parser.add_argument("--core", action="store_true", help="(install) 只装核心")
    parser.add_argument("--enhance", action="store_true", help="(install) 核心 + 增强")
    args = parser.parse_args()

    # ── 子命令：install ────────────────────────────────────────────────
    # 计划里的命令面替换（`python install.py --all` → `python main.py install --all`）。
    # 实现不在这里 —— 装什么、怎么装都问 launcher.deps，与启动期自愈共用同一份
    # 镜像轮换与依赖清单。install.py 本体的删除留到步骤 8（连同其余启动器一起），
    # 现在两条路都通向同一份实现，先把漂移消掉。
    if args.command == "install":
        return _run_install_command(args)

    # ── 子命令：nodes ──────────────────────────────────────────────────
    # 命令面替换 `python system_manager.py <cmd>` → `python main.py nodes <cmd>`。
    # 五个命令与 --group/--interval 全部照搬 system_manager.main() 的真实 argparse
    # （计划文档里写的 "<start|stop|status> [name]" 少了 monitor/report、参数形态
    #  也不对，已在 launcher/nodes.py 的模块头记录订正）。
    if args.command == "nodes":
        if not args.node_command:
            print_item("nodes 需要一个命令", "error", " | ".join(_launcher_nodes.NODE_COMMANDS))
            return _record_module().EXIT_USAGE
        return _run_nodes_command(args)

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

    from launcher import record as _record

    _exit_code = 0
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print()
        print_phase("[系统停止]")
        print_item("正在优雅关闭所有服务...", "ok")
        lumiv.stop()
        print_item("所有服务已停止", "ok")
        # 被中断不是"成功"。沿用 shell 惯例 128+SIGINT(2)=130,让自动化能区分
        # "用户按了 Ctrl+C" 和 "正常退出" —— 此前两者都返回 0。
        _exit_code = _record.EXIT_INTERRUPTED

    # 封盘：定 exit_code、落 runtime/startup.json、写日志。
    # 写失败不改变退出码（那只是排障辅助，不是启动的必要条件）。
    try:
        from launcher import ui as _ui

        _ui.finish(_exit_code, verbose=bool(os.environ.get("GALAXY_VERBOSE")), tui=False)
    except Exception:  # noqa: BLE001
        pass

    return _exit_code


if __name__ == "__main__":
    # ``raise SystemExit(main())`` 而不是裸 ``main()``。
    #
    # 此前是裸调用,于是 main() 精心算出的退出码【全部被丢弃】,进程永远 exit 0
    # —— EXIT_INTERRUPTED(130,用户按了 Ctrl+C)、EXIT_DEPENDENCY(3,依赖装不上)、
    # EXIT_USAGE(2,参数用法错)一个都到不了 shell。
    #
    # 后果与 core/health_check.py 那个"静默 exit 0"是同一类:
    # ``python main.py && next-step`` 在启动被中断或依赖缺失时照样放行,而
    # launcher/record.py 里那张退出码表读起来像是生效的。
    raise SystemExit(main())
