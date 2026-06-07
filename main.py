#!/usr/bin/env python3
# PR-WIN-ENCODING: Force UTF-8 on Windows to prevent UnicodeEncodeError in logs
import sys
import os
if sys.platform == "win32":
    # Set console to UTF-8 mode (Python 3.7+)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    # Force logging StreamHandler to use UTF-8 as well
    try:
        import io
        # Wrap stdout in a UTF-8 TextIOWrapper to ensure logging picks it up
        if hasattr(sys.stdout, "buffer"):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
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

from core.ascii_art import Colors, print_banner, print_section_header, print_status_row

# ── Phase output helpers ──────────────────────────────────
_PHASE_WIDTH = 60


def print_phase(title: str) -> None:
    """Print a Phase section title with separators."""
    print_section_header(title)
    logger.info("[Phase] %s", title)  # L2 fixed: mirror to logger


def print_item(name: str, status: str = "ok", detail: str = "") -> None:
    """Print a status item within a Phase.

    Args:
        name: Item description.
        status: "ok" | "warn" | "error" | "info".
        detail: Optional detail text shown dimmed.
    """
    icon_map = {
        "ok": ("[OK]", Colors.GREEN),
        "warn": ("[WARN]", Colors.YELLOW),
        "error": ("[ERR]", Colors.RED),
        "info": ("[INFO]", Colors.BLUE),
    }
    icon, color = icon_map.get(status, ("[*]", Colors.CYAN))
    detail_str = f"  ({Colors.DIM}{detail}{Colors.ENDC})" if detail else ""
    msg = f"  {color}{icon}{Colors.ENDC} {name}{detail_str}"
    # PR-WIN-SAFE-PRINT: Safe print for Windows cp1252 console
    try:
        print(msg)
    except UnicodeEncodeError:
        # Fallback: strip ANSI codes and encode with replace
        clean = msg.replace(Colors.GREEN, "").replace(Colors.YELLOW, "").replace(Colors.RED, "").replace(Colors.BLUE, "").replace(Colors.CYAN, "").replace(Colors.DIM, "").replace(Colors.ENDC, "")
        try:
            print(clean.encode("cp1252", errors="replace").decode("cp1252"))
        except Exception:
            pass
    # L2 fixed: mirror status items to logger (without ANSI codes)
    logger.info("[%s] %s %s", status.upper(), name, detail)


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


# PR-D6: Log rotation (10MB per file, keep 5 backups)
log_dir = PROJECT_ROOT / "logs"
log_dir.mkdir(exist_ok=True)

# SECURITY: Only configure logging if no handlers exist yet.
# Multiple entry points (main.py, galaxy_daemon.py, system_manager.py)
# call basicConfig; repeated calls are no-ops after the first.
if not logging.getLogger().handlers:
    handler = RotatingFileHandler(
        str(log_dir / "galaxy.log"), maxBytes=10 * 1024 * 1024, backupCount=5
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=[handler, SafeStreamHandler()],
    )
logger = logging.getLogger("Galaxy")

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

    status = {"ready": True}

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
            rc = sp.run(["npm", "--version"], capture_output=True, text=True, timeout=5)
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
            rc = sp.run(["node", "--version"], capture_output=True, text=True, timeout=5)
            node_ver = rc.stdout.strip() if rc.returncode == 0 else "?"
            print_item("Node.js", "ok", node_ver)
        except Exception:
            print_item("Node.js", "ok")
    else:
        print_item("Node.js 未安装", "warn")
    status["node_installed"] = node_ok

    # Electron deps
    electron_deps_ok = (ELECTRON_DIR / "node_modules").exists() if npm_ok else False
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

    # 2.0 Ensure pip is available
    if not env_status.get("pip_ok"):
        print_item("pip 未安装，正在修复...", "warn")
        pip_fixed = False
        # Method 1: ensurepip
        try:
            rc = sp.run(
                [sys.executable, "-m", "ensurepip", "--upgrade"],
                capture_output=True, text=True, timeout=60,
            ).returncode
            if rc == 0:
                pip_fixed = True
                print_item("pip 已通过 ensurepip 安装", "ok")
        except Exception:
            pass
        # Method 2: get-pip.py
        if not pip_fixed:
            try:
                rc = sp.run([
                    sys.executable, "-c",
                    "import urllib.request; "
                    "urllib.request.urlretrieve('https://bootstrap.pypa.io/get-pip.py', '/tmp/get-pip.py')",
                ], capture_output=True, text=True, timeout=30).returncode
                if rc == 0:
                    rc2 = sp.run(
                        [sys.executable, "/tmp/get-pip.py"],
                        capture_output=True, text=True, timeout=60,
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
    }
    for mod_name, pip_name in core_modules.items():
        try:
            __import__(mod_name)
        except BaseException:
            core_deps_missing.append(pip_name)

    if not core_deps_missing:
        print_item("Python 核心依赖", "ok")
    else:
        print_item(f"缺失 {len(core_deps_missing)} 个包", "warn", f"{', '.join(core_deps_missing)}")
        print_item("正在自动安装...", "ok")
        try:
            rc = sp.run(
                [sys.executable, "-m", "pip", "install", "--quiet"] + core_deps_missing,
                capture_output=True, text=True, timeout=300,
            ).returncode
            if rc == 0:
                print_item(f"已安装 {len(core_deps_missing)} 个 Python 包", "ok")
            else:
                print_item("pip install 失败", "error")
                all_ok = False
        except Exception as exc:
            print_item(f"pip install 异常: {exc}", "error")
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
            node_ver = sp.run(["node", "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
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
                    node_url = f"https://nodejs.org/dist/{node_ver}/{node_tar}"
                    node_tmp = Path("/tmp") / node_tar
                    node_dest = Path.home() / ".local" / "node"

                    print_item(f"正在下载 Node.js {node_ver}...", "ok")
                    rc = sp.run(
                        ["curl", "-fsSL", "-o", str(node_tmp), node_url],
                        capture_output=True, text=True, timeout=120,
                    ).returncode
                    if rc == 0:
                        node_dest.parent.mkdir(parents=True, exist_ok=True)
                        rc2 = sp.run(
                            ["tar", "-xf", str(node_tmp), "-C", str(node_dest.parent), "--strip-components=1"],
                            capture_output=True, text=True, timeout=30,
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

    # 2.4 Electron / npm deps
    npm_cmd = shutil.which("npm")
    if npm_cmd and not env_status.get("electron_deps_ok"):
        print_item("正在安装 Electron 依赖...", "ok")
        try:
            rc = sp.run(
                [npm_cmd, "install"],
                cwd=str(ELECTRON_DIR),
                capture_output=True, text=True, timeout=180,
            ).returncode
            if rc == 0:
                print_item("Electron 依赖安装完成", "ok")
            else:
                print_item("npm install 失败", "warn")
        except Exception as exc:
            print_item(f"npm install 异常: {exc}", "warn")

    # 2.5 Ollama install hint + model auto-download
    if not env_status.get("ollama_installed"):
        print_item("Ollama 未安装", "warn", "curl -fsSL https://ollama.com/install.sh | sh")
        print_item("  或访问: https://ollama.com/download", "info")
    else:
        print_item("正在检查 Ollama 模型...", "ok")
        try:
            rc = sp.run(
                ["ollama", "list"],
                capture_output=True, text=True, timeout=15,
            )
            if rc.returncode == 0 and rc.stdout.strip():
                models = [line.split()[0] for line in rc.stdout.strip().split("\n")[1:] if line.strip()]
                print_item(f"Ollama 模型: {len(models)} 个", "ok", ", ".join(models[:3]))
            else:
                print_item("未检测到本地模型，正在下载推荐模型...", "ok")
                rc2 = sp.run(
                    ["ollama", "pull", "gemma4:12b"],
                    capture_output=True, text=True, timeout=600,
                ).returncode
                if rc2 == 0:
                    print_item("模型 gemma4:12b 下载完成", "ok")
                else:
                    print_item("模型下载失败", "warn", "ollama pull gemma4:12b 手动重试")
        except Exception as exc:
            print_item(f"Ollama 模型检查失败: {exc}", "warn")

    # 2.6 Voice dependencies (REQUIRED)
    print_item("检查语音依赖...", "ok")
    voice_deps = {
        "pvporcupine": "pvporcupine",
        "webrtcvad": "webrtcvad",
        "faster_whisper": "faster-whisper",
    }
    voice_missing = []
    for mod_name, pip_name in voice_deps.items():
        try:
            __import__(mod_name)
        except BaseException:
            voice_missing.append(pip_name)

    if not voice_missing:
        print_item("语音依赖", "ok", "pvporcupine, webrtcvad, faster-whisper")
    else:
        print_item(f"语音依赖缺失: {', '.join(voice_missing)}", "warn")
        print_item("正在自动安装语音依赖...", "ok")
        try:
            rc = sp.run(
                [sys.executable, "-m", "pip", "install", "--quiet"] + voice_missing,
                capture_output=True, text=True, timeout=300,
            ).returncode
            if rc == 0:
                print_item("语音依赖安装完成", "ok")
            else:
                print_item("语音依赖安装失败", "warn", "麦克风支持可能不可用")
        except Exception as exc:
            print_item(f"语音依赖安装异常: {exc}", "warn")

    # pyaudio (needs system libs)
    try:
        __import__("pyaudio")
        print_item("PyAudio", "ok")
    except BaseException:
        print_item("PyAudio 未安装", "warn")
        print_item("正在自动安装 PyAudio...", "ok")
        try:
            rc = sp.run(
                [sys.executable, "-m", "pip", "install", "--quiet", "pyaudio"],
                capture_output=True, text=True, timeout=300,
            ).returncode
            if rc == 0:
                print_item("PyAudio 安装完成", "ok")
            else:
                print_item("PyAudio 安装失败", "warn", "需要系统库: apt install portaudio19-dev")
        except Exception as exc:
            print_item(f"PyAudio 安装异常: {exc}", "warn")

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

def main() -> int:
    parser = argparse.ArgumentParser(description="Galaxy V2 Unified Entry")
    parser.add_argument("--setup", action="store_true", help="Run interactive setup wizard")
    args = parser.parse_args()

    if args.setup:
        _run_setup_wizard()
        return 0

    # ── Phase 0: Galaxy Banner ───────────────────────────
    print_banner()

    # ── Phase 0: Environment check ───────────────────────
    print_phase("[Phase 0] 环境检查")
    env_status = phase0_env_check()

    # ── Phase 1: System pre-flight (original 7-phase) ───
    print_phase("[Phase 1] 系统预检")
    ready = _run_orchestrator_preflight()
    if not ready:
        print_item("系统预检未通过，请先修复上述问题", "error")
        return 1

    # ── Phase 2: Ensure dependencies ─────────────────────
    print_phase("[Phase 2] 依赖确保")
    phase2_ensure_deps(env_status)

    # ── Start unified launcher (DIRECT CALL, not subprocess)
    print_phase("[系统启动]")
    print_item("正在启动 Galaxy 后端服务...", "ok")

    from unified_launcher import GalaxyUnified

    galaxy = GalaxyUnified()
    try:
        asyncio.run(galaxy.start())
    except KeyboardInterrupt:
        print()
        print_phase("[系统停止]")
        print_item("正在优雅关闭所有服务...", "ok")
        galaxy.stop()
        print_item("所有服务已停止", "ok")

    return 0


if __name__ == "__main__":
    main()
