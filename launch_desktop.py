#!/usr/bin/env python3
# PR-WIN-ENCODING: Force UTF-8 on Windows for CJK console output.
import sys
if sys.platform == "win32":
    try:
        import io
        if hasattr(sys.stdout, "buffer"):
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
            )
            sys.stderr = io.TextIOWrapper(
                sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
            )
        import os
        os.environ["PYTHONIOENCODING"] = "utf-8:replace"
    except Exception:
        pass
"""
UFO Galaxy — 系统化完整启动器 (Systematic Launcher)
====================================================

一个入口，涵盖从 clone 到桌面 AI 对话的全部流程：

    ┌─────────────────────────────────────────────────────────────┐
    │  Phase 0: 环境检查     (Python版本, .env, pip依赖, Ollama)   │
    │  Phase 1: 依赖确保     (pip install, npm install, 模型下载)  │
    │  Phase 2: 启动 Gateway (python main.py)                     │
    │  Phase 3: 健康检查     (轮询 /health 到就绪)                │
    │  Phase 4: 启动 Electron(三态 GUI 桌面覆盖层)                │
    │  Phase 5: 运行监控     (进程保活 + 优雅退出)                │
    └─────────────────────────────────────────────────────────────┘

模型选择（首次克隆）：
    ┌─────────────────────────────────────────────────────────────┐
    │  1. Google Gemma 4 12B  — 文本+视觉+工具调用 (推荐, 默认)    │
    │  2. MiniCPM-o 4.5 9B   — 全模态边看边听边说 (实验性)       │
    │                                                              │
    │  模型在后台下载，不阻塞启动流程                              │
    │  跳过下载: --skip-model-download                             │
    └─────────────────────────────────────────────────────────────┘

用法：
    python launch_desktop.py                    # 完整启动（推荐）
    python launch_desktop.py --model gemma4:12b # 指定模型
    python launch_desktop.py --model openbmb/minicpm-o4.5
    python launch_desktop.py --skip-model-download  # 跳过模型下载
    python launch_desktop.py --check            # 只检查环境
    python launch_desktop.py --backend          # 只启动 Gateway
    python launch_desktop.py --frontend         # 只启动 Electron

退出：
    Ctrl+C → 先关 Electron → 再关 Gateway → 清理退出
"""

import argparse
import logging
import os
import platform
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Optional

from core.ascii_art import print_banner, print_section_header, print_status_row
from core.electron_launch_guard import resolve_gateway_port

# ---------------------------------------------------------------------------
# 常量配置
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.absolute()
ELECTRON_DIR = PROJECT_ROOT / "electron"
GATEWAY_HOST = os.getenv("HOST", "127.0.0.1")
GATEWAY_READY_TIMEOUT = 90
HEALTH_CHECK_INTERVAL = 1.0
ENV_FILE = PROJECT_ROOT / ".env"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"
LOGS_DIR = PROJECT_ROOT / "logs"

logger = logging.getLogger("Galaxy.Launcher")

_proc_gateway = None
_proc_electron = None
_shutting_down = False


def get_gateway_health_url() -> str:
    return f"http://{GATEWAY_HOST}:{resolve_gateway_port()}/health"

# ───────────────────────────────────────────────────────────────────────────
# 模型配置 — 用户可选择的本地模型
# ───────────────────────────────────────────────────────────────────────────

# 模型注册表与选择逻辑统一到 core.model_selection（其模型清单/尺寸取自现有
# core.local_brain_manager.LocalBrainManager —— 单一真相来源；这里只做展示适配）。
from core import model_selection as _ms

AVAILABLE_MODELS = {
    tag: {
        "name": info["name"],
        "desc": info["desc"],
        "size": (f"~{info['size_mb'] // 1000}GB" if info["size_mb"] >= 1000 else "<1GB") if info["size_mb"] else "?",
        "vram": (f"{info['size_mb'] // 1000}GB+" if info["size_mb"] >= 1000 else "1GB") if info["size_mb"] else "?",
        "recommended": False,
    }
    for tag, info in _ms.list_models()
}

DEFAULT_MODEL = _ms.DEFAULT_MODEL
_model_download_thread = None  # 后台下载线程

# ───────────────────────────────────────────────────────────────────────────
# 工具函数
# ───────────────────────────────────────────────────────────────────────────

def setup_logging(level: int = logging.INFO):
    LOGS_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOGS_DIR / "launcher.log", encoding="utf-8"),
        ],
    )


def run(cmd: list, cwd: Path = None, timeout: float = 120, capture: bool = True) -> tuple:
    """运行命令，返回 (returncode, stdout, stderr)。"""
    try:
        result = subprocess.run(
            cmd, cwd=str(cwd or PROJECT_ROOT), capture_output=capture,
            text=True, timeout=timeout,
        )
        return result.returncode, result.stdout or "", result.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except FileNotFoundError:
        return -2, "", "command not found"


def banner(title: str):
    """使用标准 Galaxy ASCII 横幅。"""
    print_banner(title)


def check_phase(name: str) -> bool:
    """检查某个阶段的结果。"""
    logger.info("  %s", name)
    return True


def fail(msg: str, hint: str = ""):
    logger.error("  ✗ %s", msg)
    if hint:
        logger.info("  → %s", hint)


def ok(msg: str):
    logger.info("  ✓ %s", msg)


def select_model_interactive() -> str:
    """交互式主脑选择 —— 委托给统一实现（硬件推荐 + 列出全部 + 手动选择）。"""
    return _ms.interactive_select()


def select_model_auto(args) -> str:
    """自动/参数化主脑选择（非交互式）：参数 > 环境变量 > 已保存 > 硬件推荐。"""
    if args.model and args.model in AVAILABLE_MODELS:
        return args.model
    env_model = os.getenv("OLLAMA_MODEL", "")
    if env_model and env_model in AVAILABLE_MODELS:
        return env_model
    config_model = _load_model_choice()
    if config_model and config_model in AVAILABLE_MODELS:
        return config_model
    try:
        return _ms.recommend()      # 4. 按 GPU/CPU 实际情况推荐
    except Exception:
        return DEFAULT_MODEL


def _load_model_choice() -> str:
    """读取用户上次选择的模型 —— 委托 core.model_selection(单一实现，见其
    .galaxy_model 持久化),不再自己重复实现一份读文件逻辑。"""
    return _ms.load_choice()


def _save_model_choice(model: str):
    """保存用户选择的模型 —— 委托 core.model_selection.save_choice()
    (同时写 .galaxy_model 和 os.environ["OLLAMA_MODEL"])。"""
    _ms.save_choice(model)


def download_model_background(model: str):
    """后台下载模型，不阻塞启动流程 —— 委托 core.model_selection.background_pull()。

    之前这里自己重新实现了一份更弱的下载逻辑:没有 /api/show 二次核实
    (只信 /api/tags 里出现了名字，可能是拉取失败留下的残缺 manifest)、
    没有 Ollama 版本过旧诊断(gemma4 系列需要较新版本，见
    core.model_selection.MIN_OLLAMA_VERSION_FOR_GEMMA4)、也没有 HuggingFace
    回退。与 core/model_selection.py 里更完整的实现是两套不同代码，用
    `python launch_desktop.py`(文档里的推荐启动方式)的用户享受不到那些
    诊断/回退。统一委托给同一个实现，不再维护第二套。
    """
    if not model or model.strip() == "":
        logger.debug("[模型下载] 空模型名，跳过下载")
        return None
    logger.info("[模型下载] 开始在后台下载 %s ...", model)
    logger.info("[模型下载] 大小约 %s，可能需要几分钟", AVAILABLE_MODELS.get(model, {}).get("size", "未知"))
    _ms.background_pull(model)
    return None


# ───────────────────────────────────────────────────────────────────────────
# Phase 0: 环境检查（精简输出版）
# ───────────────────────────────────────────────────────────────────────────

def phase0_environment_check() -> dict:
    """
    精简版环境检查。只报告关键项，不阻塞启动。
    模型状态在 Phase 1 单独处理。
    """
    banner("Phase 0: 环境检查")
    status = {
        "python_ok": False,
        "pip_ok": False,
        "env_exists": False,
        "has_api_key": False,
        "ollama_installed": False,
        "ollama_running": False,
        "model_available": False,
        "npm_installed": False,
        "electron_deps_ok": False,
        "ready": False,
    }

    issues = []   # 收集问题，最后统一报告
    ok_items = [] # 收集通过项

    # 0.1 Python 版本
    py_ver = sys.version_info
    if py_ver >= (3, 10):
        status["python_ok"] = True
        ok_items.append(f"Python {py_ver.major}.{py_ver.minor}.{py_ver.micro}")
    else:
        issues.append(f"Python {py_ver.major}.{py_ver.minor}，需要 3.10+")
        return status

    # 0.2 pip
    rc, _, _ = run([sys.executable, "-m", "pip", "--version"])
    status["pip_ok"] = rc == 0
    if status["pip_ok"]:
        ok_items.append("pip")
    else:
        issues.append("pip 不可用")

    # 0.3 .env
    status["env_exists"] = ENV_FILE.exists()
    if status["env_exists"]:
        ok_items.append(".env 已配置")

    # 0.4 API Key
    api_keys = [k for k in os.environ if "API_KEY" in k and os.environ[k].strip()
                and "your_" not in os.environ[k].lower() and "example" not in os.environ[k].lower()]
    status["has_api_key"] = len(api_keys) > 0
    if status["has_api_key"]:
        ok_items.append(f"{len(api_keys)} 个 API Key")

    # 0.5 Ollama
    ollama_cmd = shutil.which("ollama")
    status["ollama_installed"] = ollama_cmd is not None
    if status["ollama_installed"]:
        rc, _, _ = run(["ollama", "list"], timeout=5)
        status["ollama_running"] = rc == 0
        if status["ollama_running"]:
            ok_items.append("Ollama 运行中")
        else:
            issues.append("Ollama 未运行 → ollama serve &")
    else:
        issues.append("Ollama 未安装 → https://ollama.com/download")

    # 0.6 模型状态（不报告为fail，Phase 1 处理）
    if status["ollama_running"]:
        rc, out, _ = run(["ollama", "list"], timeout=5)
        # 检查是否有任何可用模型
        status["model_available"] = bool(out.strip())
        if status["model_available"]:
            installed = [line.split()[0] for line in out.strip().split('\n') if line.strip()]
            ok_items.append(f"模型: {', '.join(installed[:3])}")

    # 0.7 npm
    npm_cmd = shutil.which("npm")
    status["npm_installed"] = npm_cmd is not None
    if status["npm_installed"]:
        ok_items.append("npm")
    else:
        issues.append("npm 未安装 → https://nodejs.org")

    # 0.8 Electron 依赖
    status["electron_deps_ok"] = (ELECTRON_DIR / "node_modules" / "electron").exists()
    if status["electron_deps_ok"]:
        ok_items.append("Electron 依赖")

    # 精简输出：一行OK + 问题列表
    if ok_items:
        ok(", ".join(ok_items))
    if issues:
        logger.warning("  ⚠ %d 个问题（不影响启动）:", len(issues))
        for issue in issues:
            logger.warning("     → %s", issue)

    # 总结：只有核心项缺失才阻止启动
    critical_ok = status["python_ok"] and status["pip_ok"] and status["npm_installed"]
    can_run = critical_ok
    if not can_run:
        fail("核心依赖缺失，无法启动。请修复后重试。")
    status["ready"] = can_run
    return status


# ───────────────────────────────────────────────────────────────────────────
# Phase 1: 依赖确保
# ───────────────────────────────────────────────────────────────────────────

def phase1_ensure_dependencies(status: dict, args) -> bool:
    """自动修复能修复的依赖问题。"""
    banner("Phase 1: 依赖确保")
    all_ok = True

    # 1.1 Python 依赖
    logger.info("  检查 Python 依赖...")
    rc, _, _ = run([sys.executable, "-c", "import fastapi, uvicorn, websockets, pydantic"], timeout=15)
    if rc == 0:
        ok("Python 核心依赖已安装 ✓")
    else:
        logger.info("  → pip install -r requirements.txt ...")
        rc, out, err = run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], timeout=300, capture=True)
        if rc == 0:
            ok("Python 依赖安装完成 ✓")
        else:
            fail(f"pip install 失败: {err[:200]}")
            all_ok = False

    # 1.2 .env 文件
    if not status["env_exists"] and ENV_EXAMPLE.exists():
        logger.info("  从 .env.example 创建 .env ...")
        shutil.copy(ENV_EXAMPLE, ENV_FILE)
        ok(".env 已创建，请编辑配置你的 API Key")
        logger.info("  → 编辑命令: nano .env 或 vim .env")

    # 1.3 Ollama 模型 — 后台下载，不阻塞启动
    if status["ollama_installed"] and not status["model_available"]:
        # 选择模型
        model = select_model_auto(args)
        
        # 交互式选择（首次启动且是TTY）
        if not _load_model_choice() and sys.stdin.isatty() and not getattr(args, 'no_interactive', False):
            model = select_model_interactive()
            if model:
                _save_model_choice(model)
        
        if not model or args.skip_model_download:
            logger.info("  → 跳过模型下载（可用云端 API 或稍后 ollama pull）")
        else:
            info = AVAILABLE_MODELS.get(model, {})
            logger.info("  → %s (%s)", info.get('name', model), info.get('size', '?'))
            logger.info("  → 后台下载中，启动不受影响...")
            _model_download_thread = download_model_background(model)
            # 不等待下载完成，继续启动流程
            status["model_available"] = True  # 标记为可用（启动后下载完即可用）

    # 1.4 Electron 依赖
    if not status["electron_deps_ok"]:
        logger.info("  cd electron && npm install ...")
        rc, out, err = run(["npm", "install"], cwd=ELECTRON_DIR, timeout=120, capture=True)
        if rc == 0:
            ok("Electron 依赖安装完成 ✓")
            status["electron_deps_ok"] = True
        else:
            fail(f"npm install 失败: {err[:200]}")
            all_ok = False

    return all_ok


# ───────────────────────────────────────────────────────────────────────────
# Phase 2-5: 启动流程（同之前，日志改写到文件）
# ───────────────────────────────────────────────────────────────────────────

def gateway_is_ready() -> bool:
    try:
        with urllib.request.urlopen(get_gateway_health_url(), timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def wait_for_gateway(timeout: float = GATEWAY_READY_TIMEOUT) -> bool:
    start = time.time()
    dots = 0
    while time.time() - start < timeout:
        if gateway_is_ready():
            return True
        time.sleep(HEALTH_CHECK_INTERVAL)
        dots += 1
        if dots % 5 == 0:
            logger.info("    ... 等待中 (%ds)", int(time.time() - start))
    return False


def kill_proc(proc, name, timeout=5.0):
    if proc is None or proc.poll() is not None:
        return
    logger.info("[%s] 正在停止...", name)
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    finally:
        # 关闭日志文件句柄
        if hasattr(proc, '_stdout_handle'):
            try:
                proc._stdout_handle.close()
            except Exception:
                pass


def _signal_handler(signum, frame):
    global _shutting_down
    if _shutting_down:
        return
    _shutting_down = True
    logger.info("")
    banner("收到退出信号，正在优雅关闭...")
    kill_proc(_proc_electron, "Electron")
    kill_proc(_proc_gateway, "Gateway")
    logger.info("已退出。")
    sys.exit(0)


def start_gateway_backend():
    """委托 main.py 启动后端。"""
    env = os.environ.copy()
    gateway_port = resolve_gateway_port()
    env["GALAXY_GATEWAY_PORT"] = str(gateway_port)
    env["PORT"] = str(gateway_port)
    env["PYTHONUNBUFFERED"] = "1"
    gateway_log = LOGS_DIR / "gateway.log"
    gateway_log.parent.mkdir(exist_ok=True)
    # PR-FH: ensure handle closed even if Popen raises
    _gateway_stdout = open(gateway_log, "w", encoding="utf-8")
    _proc = None
    try:
        _proc = subprocess.Popen(
            [sys.executable, str(PROJECT_ROOT / "main.py"), "--host", GATEWAY_HOST, "--port", str(gateway_port)],
            cwd=str(PROJECT_ROOT), env=env,
            stdout=_gateway_stdout, stderr=subprocess.STDOUT,
        )
        _proc._stdout_handle = _gateway_stdout
        return _proc
    except Exception:
        _gateway_stdout.close()
        if _proc is not None:
            try:
                _proc.kill()
            except Exception:
                pass
        raise


def start_electron_frontend() -> Optional[subprocess.Popen]:
    from core.electron_launch_guard import already_running, resolve_gateway_port, write_lock

    # PR-ELECTRON-DEDUP: start_gateway_backend() 把整个 `python main.py` 拉起为子
    # 进程,而 main.py 内部本身就含两条桌面壳启动路径(Phase 6 + unified_launcher)。
    # 之前这里毫不知情地再起第三次,单次 `python launch_desktop.py` 最多触发 3 次
    # 独立的 Electron 拉起尝试。共享同一把锁后,只要 main.py 子进程内部已经成功
    # 拉起(通常会更快抢到锁),这里直接跳过。
    if already_running():
        logger.info("  Electron 桌面覆盖层已由后端子进程拉起，跳过重复启动")
        return None

    logger.info("  启动 Electron 桌面覆盖层...")
    from core.electron_launch_guard import electron_package_intact
    node_modules = ELECTRON_DIR / "node_modules"
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("npm 未安装")
    # 不能只看目录存在——中断安装的残局(.bin 存根在、electron/cli.js 缺失)
    # 直接拉起必然 MODULE_NOT_FOUND 崩溃,需重跑 npm install 修复。
    if not node_modules.exists() or not electron_package_intact(str(ELECTRON_DIR)):
        logger.info("  → 依赖缺失或不完整，执行 npm install ...")
        rc, _, err = run([npm, "install"], cwd=ELECTRON_DIR, timeout=300)
        if rc != 0:
            raise RuntimeError(f"npm install 失败: {err[:200]}")

    npx = shutil.which("npx") or npm
    env = os.environ.copy()
    env["ELECTRON_ENABLE_LOGGING"] = "1"
    env["PATH"] = str(Path(npm).parent) + os.pathsep + env.get("PATH", "")
    # 同步真实网关端口给 Electron——之前这里完全不注入,Electron 只能猜默认 9000。
    env["GALAXY_GATEWAY_PORT"] = str(resolve_gateway_port())
    env.setdefault("PORT", env["GALAXY_GATEWAY_PORT"])
    # PR-WIN-ELECTRON: Windows needs DETACHED_PROCESS for clean Electron start
    popen_kwargs = {}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    proc = subprocess.Popen([npx, "electron", "."], cwd=str(ELECTRON_DIR), env=env,
                            stdout=None, stderr=None, **popen_kwargs)
    write_lock(proc.pid)
    return proc


def start_tauri_frontend() -> Optional[subprocess.Popen]:
    """优先启动 Tauri 壳（系统 WebView，远轻于 Electron：内存/启动/体积都小得多）。
    无二进制且有 cargo → 自动构建一次(cargo build --release)后启动；无 cargo / 构建失败 /
    GALAXY_TAURI_AUTOBUILD=0 / GALAXY_DESKTOP_SHELL=electron → 返回 None，由调用方回退 Electron。
    env 与 Electron 注入完全一致（端口/锁），托盘与后端 bridge 无需改动。"""
    from core.electron_launch_guard import already_running, resolve_gateway_port, write_lock
    if os.environ.get("GALAXY_DESKTOP_SHELL", "").strip().lower() == "electron":
        return None
    if already_running():
        logger.info("  桌面壳已由其他路径拉起，跳过 Tauri 启动")
        return None
    tdir = PROJECT_ROOT / "desktop-tauri"
    if not tdir.exists():
        return None
    exe = "galaxy-overlay.exe" if os.name == "nt" else "galaxy-overlay"
    candidates = [
        tdir / "src-tauri" / "target" / "release" / exe,
        tdir / "src-tauri" / "target" / "debug" / exe,
    ]
    binp = next((c for c in candidates if c.exists()), None)
    if binp is None:
        optout = os.environ.get("GALAXY_TAURI_AUTOBUILD", "").strip().lower() in (
            "0", "false", "no", "off",
        )
        if optout or shutil.which("cargo") is None:
            logger.info(
                "  Tauri 无二进制且不自动构建 → 回退 Electron"
                "（装 Rust(https://rustup.rs) 后重启即自动构建并优先 Tauri）"
            )
            return None
        # 构建前预检系统级依赖（Linux 的 webkit2gtk 等）——缺则给出 apt 命令、跳过、回退 Electron。
        try:
            from core.electron_launch_guard import tauri_build_prereqs_hint
            _hint = tauri_build_prereqs_hint()
        except Exception:
            _hint = None
        if _hint:
            logger.info(f"  Tauri 构建系统依赖缺失，跳过自动构建 → 回退 Electron：\n{_hint}")
            return None
        logger.info("  首次启动：自动构建 Tauri 桌面壳(cargo build --release，首次约数分钟)…")
        rc, _, err = run(["cargo", "build", "--release"], cwd=str(tdir / "src-tauri"), timeout=1800)
        if rc != 0:
            logger.info(f"  Tauri 构建失败(rc={rc}) → 回退 Electron")
            return None
        binp = next((c for c in candidates if c.exists()), None)
        if binp is None:
            return None
        logger.info("  Tauri 壳构建完成 ✓ 之后启动将自动优先用它")

    logger.info("  启动 Tauri 桌面覆盖层（轻量壳）...")
    env = os.environ.copy()
    env["GALAXY_GATEWAY_PORT"] = str(resolve_gateway_port())
    env.setdefault("PORT", env["GALAXY_GATEWAY_PORT"])
    popen_kwargs = {}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    proc = subprocess.Popen([str(binp)], cwd=str(tdir / "src-tauri"), env=env, **popen_kwargs)
    write_lock(proc.pid)
    return proc


def start_desktop_shell() -> Optional[subprocess.Popen]:
    """统一桌面壳入口：优先 Tauri（轻量），无则回退 Electron。"""
    return start_tauri_frontend() or start_electron_frontend()


# ───────────────────────────────────────────────────────────────────────────
# 主流程
# ───────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="UFO Galaxy 系统化完整启动器")
    parser.add_argument("--check", action="store_true", help="只检查环境，不启动")
    parser.add_argument("--backend", action="store_true", help="只启动 Gateway")
    parser.add_argument("--frontend", action="store_true", help="只启动 Electron")
    parser.add_argument("--docker", action="store_true", help="Docker 模式")
    parser.add_argument("--debug", action="store_true", help="DEBUG 日志")
    parser.add_argument("--skip-check", action="store_true", help="跳过环境检查（快速启动）")
    parser.add_argument("--model", choices=list(AVAILABLE_MODELS.keys()),
                        default=os.getenv("OLLAMA_MODEL", DEFAULT_MODEL),
                        help=f"选择本地模型 (默认: {DEFAULT_MODEL})")
    parser.add_argument("--skip-model-download", action="store_true",
                        help="跳过模型下载（使用云端 API 或稍后手动下载）")
    parser.add_argument("--no-interactive", action="store_true",
                        help="非交互模式（使用默认配置，不提示选择）")
    parser.add_argument("--list-models", action="store_true",
                        help="列出可用的本地模型并退出")
    args = parser.parse_args()

    # --list-models: 列出模型并退出
    if args.list_models:
        print("\n  可用本地模型:\n")
        for tag, info in AVAILABLE_MODELS.items():
            rec = " ★ 推荐" if info["recommended"] else ""
            print(f"  {tag:20s} — {info['name']:25s} {rec}")
            print(f"  {'':20s}   {info['desc']}")
            print(f"  {'':20s}   大小: {info['size']} | VRAM: {info['vram']}")
            print()
        print(f"  默认模型: {DEFAULT_MODEL}")
        print(f"  设置环境变量: export OLLAMA_MODEL=<模型名>")
        sys.exit(0)

    setup_logging(logging.DEBUG if args.debug else logging.INFO)

    # 注册信号处理
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _signal_handler)

    # ── 模式：只检查 ──
    if args.check:
        status = phase0_environment_check()
        sys.exit(0 if status["ready"] else 1)

    # ── 模式：只启动前端 ──
    if args.frontend:
        if not gateway_is_ready():
            logger.error("Gateway 未在 %s 响应", get_gateway_health_url())
            sys.exit(1)
        global _proc_electron
        _proc_electron = start_desktop_shell()
        if _proc_electron is None:
            logger.info("桌面覆盖层已由其他启动路径拉起，本进程无需再等待")
            return
        _proc_electron.wait()
        return

    # ── 模式：只启动后端 ──
    if args.backend:
        logger.info("正在启动 Gateway（委托 main.py）...")
        _proc_gateway = start_gateway_backend()
        # PR-POPEN-FIX: start_gateway_backend() returns a Popen object, not a tuple
        try:
            _proc_gateway.wait()
            sys.exit(_proc_gateway.returncode if _proc_gateway.returncode is not None else 0)
        except KeyboardInterrupt:
            kill_proc(_proc_gateway, "Gateway")
            sys.exit(0)

    # ═══════════════════════════════════════════════════════════════════
    # 完整模式：系统化一体化启动
    # ═══════════════════════════════════════════════════════════════════
    print()
    print("  ╔═══════════════════════════════════════════════════════════╗")
    chosen_model = select_model_auto(args)
    model_info = AVAILABLE_MODELS.get(chosen_model, {})
    model_display = model_info.get('name', chosen_model) if model_info else chosen_model
    print("  ║      UFO Galaxy 桌面原生 AI 助手 — 系统化启动器          ║")
    print(f"  ║      本地模型: {model_display:43s} ║")
    print("  ╚═══════════════════════════════════════════════════════════╝")
    print()

    # Phase 0: 环境检查
    status = phase0_environment_check() if not args.skip_check else {"ready": True}
    if not status.get("ready"):
        logger.info("")
        logger.info("正在自动修复可修复的问题...")

    # Phase 1: 依赖确保
    if not phase1_ensure_dependencies(status, args):
        logger.error("依赖修复失败，请手动检查后重试。")
        sys.exit(1)

    # 启动后端（委托 main.py）
    logger.info("正在启动 Gateway（委托 main.py）...")
    _proc_gateway = start_gateway_backend()
    logger.info("  Gateway PID=%d | 日志: logs/gateway.log", _proc_gateway.pid)

    # Phase 3: 健康检查
    banner("Phase 3: 等待 Gateway 就绪")
    if not wait_for_gateway():
        logger.error("Gateway 在 %ds 内未就绪。", GATEWAY_READY_TIMEOUT)
        logger.info("查看日志: tail -f logs/gateway.log")
        kill_proc(_proc_gateway, "Gateway")
        sys.exit(1)
    ok("Gateway 就绪 ✓")
    gateway_port = resolve_gateway_port()
    logger.info("  WebSocket: ws://%s:%d/ws/desktop-presence", GATEWAY_HOST, gateway_port)
    logger.info("  REST API:  http://%s:%d/api/v1/", GATEWAY_HOST, gateway_port)

    # Phase 4: 启动 Electron
    banner("Phase 4: 启动三态桌面覆盖层")
    try:
        _proc_electron = start_desktop_shell()
        if _proc_electron is not None:
            ok(f"Electron 启动 ✓ PID={_proc_electron.pid}")
        else:
            ok("Electron 已由后端子进程内部启动路径拉起 ✓")
    except RuntimeError as e:
        fail(str(e))
        kill_proc(_proc_gateway, "Gateway")
        sys.exit(1)

    # Phase 5: 运行监控
    banner("Phase 5: 运行监控 — 按 Ctrl+C 退出")
    logger.info("  操作指南:")
    logger.info("    Ctrl+Space  = 唤醒 AI (SILENT → LIMINAL)")
    logger.info("    F12         = 打开/关闭控制面板")
    logger.info("    Esc         = 关闭结果面板 (MANIFEST → SILENT)")
    logger.info("    Ctrl+C      = 完全退出")
    logger.info("")

    try:
        while True:
            if _proc_gateway.poll() is not None:
                logger.error("Gateway 意外退出 (code=%d)", _proc_gateway.returncode)
                logger.info("查看日志: tail -f logs/gateway.log")
                kill_proc(_proc_electron, "Electron")
                sys.exit(1)

            if _proc_electron is not None and _proc_electron.poll() is not None:
                code = _proc_electron.returncode
                logger.warning("Electron 已退出 (code=%d)", code)
                logger.info("Gateway 仍在后台运行。按 Ctrl+C 完全退出。")
                break

            time.sleep(1.0)
    except KeyboardInterrupt:
        pass

    if not _shutting_down:
        _signal_handler(signal.SIGTERM, None)


if __name__ == "__main__":
    main()