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
    python launch_desktop.py --model minicpm-o4.5:9b
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

from core.ascii_art import print_banner, print_section_header, print_status_row

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
# 模型配置 — 用户可选择的本地模型
# ───────────────────────────────────────────────────────────────────────────

AVAILABLE_MODELS = {
    "gemma4:12b": {
        "name": "Google Gemma 4 12B",
        "desc": "文本+视觉+原生工具调用，128K上下文",
        "size": "~8GB",
        "vram": "8GB+",
        "recommended": True,
    },
    "minicpm-o4.5:9b": {
        "name": "MiniCPM-o 4.5 9B",
        "desc": "全模态(看+听+说)，全双工实时交互",
        "size": "~6GB",
        "vram": "9GB+",
        "recommended": False,
    },
}

DEFAULT_MODEL = "gemma4:12b"
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
    """交互式模型选择 — 首次克隆时让用户选择要下载的模型。"""
    print()
    print("  ╔═══════════════════════════════════════════════════════════╗")
    print("  ║  选择本地 AI 模型（首次启动需要下载，约 2-8GB）         ║")
    print("  ╚═══════════════════════════════════════════════════════════╝")
    print()
    
    models = list(AVAILABLE_MODELS.items())
    for i, (tag, info) in enumerate(models, 1):
        rec = " [推荐]" if info["recommended"] else ""
        print(f"  [{i}] {info['name']}{rec}")
        print(f"      {info['desc']}")
        print(f"      大小: {info['size']} | VRAM: {info['vram']}")
        print()
    
    print("  [s] 跳过模型下载（稍后手动执行: ollama pull <模型>）")
    print()
    
    while True:
        choice = input("  请选择 [1/2/s，默认 1]: ").strip().lower()
        if choice == "" or choice == "1":
            return models[0][0]
        elif choice == "2" and len(models) >= 2:
            return models[1][0]
        elif choice == "s":
            return ""
        else:
            print("  无效选择，请重试。")


def select_model_auto(args) -> str:
    """自动/参数化模型选择（非交互式）。"""
    # 1. 命令行参数指定
    if args.model and args.model in AVAILABLE_MODELS:
        return args.model
    # 2. 环境变量指定
    env_model = os.getenv("OLLAMA_MODEL", "")
    if env_model and env_model in AVAILABLE_MODELS:
        return env_model
    # 3. 配置文件中的已选模型
    config_model = _load_model_choice()
    if config_model and config_model in AVAILABLE_MODELS:
        return config_model
    # 4. 默认推荐模型
    return DEFAULT_MODEL


def _load_model_choice() -> str:
    """从 .galaxy_config 读取用户上次选择的模型。"""
    config_file = PROJECT_ROOT / ".galaxy_model"
    if config_file.exists():
        return config_file.read_text().strip()
    return ""


def _save_model_choice(model: str):
    """保存用户选择的模型到 .galaxy_model。"""
    config_file = PROJECT_ROOT / ".galaxy_model"
    config_file.write_text(model)


def download_model_background(model: str):
    """后台线程下载模型，不阻塞启动流程。"""
    def _download():
        logger.info("[模型下载] 开始在后台下载 %s ...", model)
        logger.info("[模型下载] 大小约 %s，可能需要几分钟", AVAILABLE_MODELS.get(model, {}).get("size", "未知"))
        try:
            result = subprocess.run(
                ["ollama", "pull", model],
                capture_output=True, text=True, timeout=1800,  # 30分钟超时
            )
            if result.returncode == 0:
                logger.info("[模型下载] ✅ %s 下载完成！", model)
                _save_model_choice(model)
            else:
                logger.warning("[模型下载] ⚠️ 下载失败: %s", result.stderr[:200] if result.stderr else "未知错误")
                logger.info("[模型下载] 可稍后手动执行: ollama pull %s", model)
        except subprocess.TimeoutExpired:
            logger.warning("[模型下载] ⏱️ 下载超时(30分钟)，仍在继续后台下载...")
            logger.info("[模型下载] 可稍后手动执行: ollama pull %s", model)
        except Exception as e:
            logger.warning("[模型下载] ❌ 异常: %s", str(e)[:200])
            logger.info("[模型下载] 可稍后手动执行: ollama pull %s", model)
    
    thread = threading.Thread(target=_download, daemon=True, name=f"ModelDownload-{model}")
    thread.start()
    return thread


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


def start_gateway_backend():
    """委托 main.py 启动后端。"""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    gateway_log = LOGS_DIR / "gateway.log"
    gateway_log.parent.mkdir(exist_ok=True)
    stdout = open(gateway_log, "w", encoding="utf-8")
    return subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "main.py")],
        cwd=str(PROJECT_ROOT), env=env,
        stdout=stdout, stderr=subprocess.STDOUT,
    )


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
            logger.error("Gateway 未在 %s 响应", GATEWAY_HEALTH_URL)
            sys.exit(1)
        global _proc_electron
        _proc_electron = start_electron_frontend()
        _proc_electron.wait()
        return

    # ── 模式：只启动后端 ──
    if args.backend:
        logger.info("正在启动 Gateway（委托 main.py）...")
        _proc_gateway = start_gateway_backend()
        returncode, _, _ = _proc_gateway
        sys.exit(returncode)

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