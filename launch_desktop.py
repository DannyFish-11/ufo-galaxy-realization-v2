#!/usr/bin/env python3
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

用法：
    python launch_desktop.py              # 完整启动（推荐）
    python launch_desktop.py --check      # 只检查环境，不启动
    python launch_desktop.py --backend    # 只启动 Gateway
    python launch_desktop.py --frontend   # 只启动 Electron
    python launch_desktop.py --docker     # Docker 模式

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
import time
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# 常量配置
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.absolute()
ELECTRON_DIR = PROJECT_ROOT / "electron"
GATEWAY_PORT = int(os.getenv("PORT", "8765"))
GATEWAY_HOST = os.getenv("HOST", "127.0.0.1")
GATEWAY_HEALTH_URL = f"http://{GATEWAY_HOST}:{GATEWAY_PORT}/health"
GATEWAY_READY_TIMEOUT = 90
HEALTH_CHECK_INTERVAL = 1.0
ENV_FILE = PROJECT_ROOT / ".env"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"
LOGS_DIR = PROJECT_ROOT / "logs"

logger = logging.getLogger("Galaxy.Launcher")

_proc_gateway = None
_proc_electron = None
_shutting_down = False

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
    logger.info("=" * 56)
    logger.info("  %s", title)
    logger.info("=" * 56)


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


# ───────────────────────────────────────────────────────────────────────────
# Phase 0: 环境检查
# ───────────────────────────────────────────────────────────────────────────

def phase0_environment_check() -> dict:
    """
    全面检查运行环境，返回状态字典。
    不修改任何东西，只检查并报告。
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

    # 0.1 Python 版本
    py_ver = sys.version_info
    if py_ver >= (3, 10):
        status["python_ok"] = True
        ok(f"Python {py_ver.major}.{py_ver.minor}.{py_ver.micro} ✓")
    else:
        fail(f"Python {py_ver.major}.{py_ver.minor}，需要 3.10+")
        return status

    # 0.2 pip 可用
    rc, _, _ = run([sys.executable, "-m", "pip", "--version"])
    status["pip_ok"] = rc == 0
    if status["pip_ok"]:
        ok("pip 可用 ✓")
    else:
        fail("pip 不可用")

    # 0.3 .env 文件
    status["env_exists"] = ENV_FILE.exists()
    if status["env_exists"]:
        ok(f".env 已配置 ✓ ({ENV_FILE})")
    else:
        fail(f".env 不存在", f"cp .env.example .env  然后编辑配置你的 API Key")

    # 0.4 API Key 检查
    api_keys = [k for k in os.environ if "API_KEY" in k and os.environ[k].strip()
                and "your_" not in os.environ[k].lower() and "example" not in os.environ[k].lower()]
    status["has_api_key"] = len(api_keys) > 0
    if status["has_api_key"]:
        ok(f"已配置 {len(api_keys)} 个 API Key ✓")
    else:
        if status["env_exists"]:
            fail("API Key 未配置（.env 中的值仍是占位符）")
        logger.info("  → 至少配置一个: OPENAI_API_KEY 或 DEEPSEEK_API_KEY")

    # 0.5 Ollama 安装
    ollama_cmd = shutil.which("ollama")
    status["ollama_installed"] = ollama_cmd is not None
    if status["ollama_installed"]:
        ok(f"Ollama 已安装 ✓ ({ollama_cmd})")
    else:
        fail("Ollama 未安装", "https://ollama.com/download 下载安装")

    # 0.6 Ollama 运行
    if status["ollama_installed"]:
        rc, _, _ = run(["ollama", "list"], timeout=5)
        status["ollama_running"] = rc == 0
        if status["ollama_running"]:
            ok("Ollama 服务运行中 ✓")
        else:
            fail("Ollama 未运行", "ollama serve &")

    # 0.7 Gemma 4 模型
    if status["ollama_running"]:
        model = os.getenv("OLLAMA_MODEL", "gemma4:latest")
        rc, out, _ = run(["ollama", "list"], timeout=5)
        status["model_available"] = model in out
        if status["model_available"]:
            ok(f"模型 {model} 已下载 ✓")
        else:
            fail(f"模型 {model} 未下载", f"ollama pull {model}")

    # 0.8 npm
    npm_cmd = shutil.which("npm")
    status["npm_installed"] = npm_cmd is not None
    if status["npm_installed"]:
        ok(f"npm 可用 ✓")
    else:
        fail("npm 未安装", "安装 Node.js 18+: https://nodejs.org")

    # 0.9 Electron 依赖
    status["electron_deps_ok"] = (ELECTRON_DIR / "node_modules" / "electron").exists()
    if status["electron_deps_ok"]:
        ok("Electron 依赖已安装 ✓")
    else:
        fail("Electron 依赖未安装", "cd electron && npm install")

    # 总结
    critical = ["python_ok", "pip_ok", "npm_installed"]
    optional = ["ollama_installed", "has_api_key"]  # 至少有一个就能跑
    critical_ok = all(status[k] for k in critical)
    can_run = critical_ok and (status["has_api_key"] or status["model_available"])

    if can_run:
        ok("环境检查通过，可以启动")
    else:
        fail("环境检查未通过，请修复上述问题后重试")
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

    # 1.3 Ollama 模型
    if status["ollama_installed"] and not status["model_available"]:
        model = os.getenv("OLLAMA_MODEL", "gemma4:latest")
        logger.info("  下载 %s ...（首次需要，约 2-5GB）", model)
        rc, out, err = run(["ollama", "pull", model], timeout=600, capture=True)
        if rc == 0:
            ok(f"模型 {model} 下载完成 ✓")
            status["model_available"] = True
        else:
            fail(f"模型下载失败: {err[:200]}")

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
        with urllib.request.urlopen(GATEWAY_HEALTH_URL, timeout=2) as resp:
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


def start_gateway_backend(docker_mode: bool) -> subprocess.Popen:
    if docker_mode:
        logger.info("  启动 Galaxy Gateway (Docker)...")
        cmd = ["docker", "compose", "up", "-d", "galaxy-gateway"]
    else:
        logger.info("  启动 Galaxy Gateway (Python)...")
        cmd = [sys.executable, str(PROJECT_ROOT / "main.py")]

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    if docker_mode:
        # Docker 模式：日志直接输出
        stdout = None
    else:
        # Python 模式：Gateway 日志写入文件，启动器只显示状态
        gateway_log = LOGS_DIR / "gateway.log"
        gateway_log.parent.mkdir(exist_ok=True)
        stdout = open(gateway_log, "w", encoding="utf-8")

    return subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), env=env,
                            stdout=stdout, stderr=subprocess.STDOUT)


def start_electron_frontend() -> subprocess.Popen:
    logger.info("  启动 Electron 桌面覆盖层...")
    node_modules = ELECTRON_DIR / "node_modules"
    if not node_modules.exists():
        logger.info("  → 首次运行，执行 npm install ...")
        rc, _, err = run(["npm", "install"], cwd=ELECTRON_DIR, timeout=120)
        if rc != 0:
            raise RuntimeError(f"npm install 失败: {err[:200]}")

    env = os.environ.copy()
    env["ELECTRON_ENABLE_LOGGING"] = "1"
    return subprocess.Popen(["npx", "electron", "."], cwd=str(ELECTRON_DIR), env=env,
                            stdout=None, stderr=None)


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
    args = parser.parse_args()

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
            logger.error("Gateway 未在 %s 响应", GATEWAY_HEALTH_URL)
            sys.exit(1)
        global _proc_electron
        _proc_electron = start_electron_frontend()
        _proc_electron.wait()
        return

    # ── 模式：只启动后端 ──
    if args.backend:
        global _proc_gateway
        _proc_gateway = start_gateway_backend(args.docker)
        _proc_gateway.wait()
        return

    # ═══════════════════════════════════════════════════════════════════
    # 完整模式：系统化一体化启动
    # ═══════════════════════════════════════════════════════════════════
    print()
    print("  ╔═══════════════════════════════════════════════════════════╗")
    print("  ║      UFO Galaxy 桌面原生 AI 助手 — 系统化启动器          ║")
    print("  ║      本地模型: Google Gemma 4 E4B (128K 上下文)          ║")
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

    # Phase 2: 启动 Gateway
    banner("Phase 2: 启动 Galaxy Gateway")
    _proc_gateway = start_gateway_backend(args.docker)
    logger.info("  Gateway PID=%d | 日志: logs/gateway.log", _proc_gateway.pid)

    # Phase 3: 健康检查
    banner("Phase 3: 等待 Gateway 就绪")
    if not wait_for_gateway():
        logger.error("Gateway 在 %ds 内未就绪。", GATEWAY_READY_TIMEOUT)
        logger.info("查看日志: tail -f logs/gateway.log")
        kill_proc(_proc_gateway, "Gateway")
        sys.exit(1)
    ok("Gateway 就绪 ✓")
    logger.info("  WebSocket: ws://%s:%d/ws/desktop-presence", GATEWAY_HOST, GATEWAY_PORT)
    logger.info("  REST API:  http://%s:%d/api/v1/", GATEWAY_HOST, GATEWAY_PORT)

    # Phase 4: 启动 Electron
    banner("Phase 4: 启动三态桌面覆盖层")
    try:
        _proc_electron = start_electron_frontend()
        ok(f"Electron 启动 ✓ PID={_proc_electron.pid}")
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

            if _proc_electron.poll() is not None:
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
