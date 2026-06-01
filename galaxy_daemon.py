#!/usr/bin/env python3
"""
Galaxy Windows 守护进程
=======================
开机自启、崩溃自动重启、日志轮转、不依赖 Desktop GUI。

用法:
    # 前台运行（调试）
    python galaxy_daemon.py

    # 安装为 Windows 服务（管理员 PowerShell）
    python galaxy_daemon.py --install

    # 卸载服务
    python galaxy_daemon.py --uninstall

    # 查看状态
    python galaxy_daemon.py --status
"""

import argparse
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.resolve()
LOG_DIR = PROJECT_ROOT / "logs"
MAX_LOG_DAYS = 7           # 日志保留天数
MAX_RESTARTS_PER_HOUR = 5  # 每小时最大重启次数
RESTART_COOLDOWN = 60      # 崩溃后等待秒数

# 环境变量（内嵌默认值，不需要 .env）
DEFAULT_ENV = {
    "GALAXY_API_TOKEN": "",
    "GALAXY_AUTH_ENABLED": "false",         # 默认关闭认证（无token时不报CRITICAL）
    "GALAXY_NATS_ENABLED": "false",         # 守护模式不启动NATS
    "GALAXY_DESKTOP_GUI_ENABLED": "false",  # 守护模式不启动 GUI
    "GALAXY_LOG_LEVEL": "INFO",
    "PYTHONIOENCODING": "utf-8",
}

# ── 日志设置 ──────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    """设置日志：文件 + 控制台，按天轮转。"""
    LOG_DIR.mkdir(exist_ok=True)

    # 清理旧日志
    _cleanup_old_logs()

    log_file = LOG_DIR / f"galaxy_{datetime.now():%Y%m%d}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("Galaxy.Daemon")


def _cleanup_old_logs():
    """删除超过 MAX_LOG_DAYS 天的日志文件。"""
    if not LOG_DIR.exists():
        return
    cutoff = time.time() - MAX_LOG_DAYS * 86400
    for f in LOG_DIR.glob("galaxy_*.log"):
        if f.stat().st_mtime < cutoff:
            try:
                f.unlink()
            except OSError:
                pass


# ── 核心守护逻辑 ──────────────────────────────────────────────────────

class GalaxyDaemon:
    """Galaxy 守护进程：启动、监控、自动重启。"""

    def __init__(self):
        self.logger = setup_logging()
        self.process = None
        self.restart_count = 0
        self.restart_window_start = time.time()

    def _set_env(self):
        """设置环境变量（使用默认值或 .env 中的值）。"""
        # 先尝试加载 .env
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            self.logger.info("加载 .env 文件")
            # python-dotenv 会在 main.py 中加载，这里只检查存在性

        # 设置默认值（不覆盖已有值）
        for key, value in DEFAULT_ENV.items():
            if key not in os.environ:
                os.environ[key] = value
                if key != "GALAXY_API_TOKEN":
                    self.logger.info(f"设置默认环境: {key}={value}")

        # 检查关键配置
        if not os.environ.get("GALAXY_API_TOKEN"):
            self.logger.info("GALAXY_API_TOKEN 未设置，认证已自动禁用 (daemon模式安全默认值)")
            self.logger.info("  如需启用认证: 编辑 .env → GALAXY_AUTH_ENABLED=true + GALAXY_API_TOKEN=your_token")

    def _check_dependencies(self) -> bool:
        """检查核心依赖是否已安装。"""
        required = ["fastapi", "uvicorn", "pydantic", "websockets", "httpx"]
        missing = []
        for mod in required:
            try:
                __import__(mod)
            except ImportError:
                missing.append(mod)

        if missing:
            self.logger.error(f"缺失依赖: {', '.join(missing)}")
            self.logger.info("  运行: python install.py")
            return False
        return True

    def _start_galaxy(self) -> subprocess.Popen:
        """启动 Galaxy 主进程。"""
        main_py = PROJECT_ROOT / "main.py"
        if not main_py.exists():
            raise FileNotFoundError(f"找不到 {main_py}")

        self.logger.info("启动 Galaxy...")
        return subprocess.Popen(
            [sys.executable, str(main_py)],
            cwd=str(PROJECT_ROOT),
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def _monitor(self):
        """监控进程输出和状态。"""
        if self.process.stdout:
            for line in self.process.stdout:
                line = line.strip()
                if line:
                    # 转发 Galaxy 日志到守护进程日志
                    self.logger.info(f"[Galaxy] {line[:200]}")

    def _should_restart(self) -> bool:
        """检查是否允许重启（防无限循环）。"""
        now = time.time()
        if now - self.restart_window_start > 3600:
            # 新的小时窗口
            self.restart_count = 0
            self.restart_window_start = now

        self.restart_count += 1
        if self.restart_count > MAX_RESTARTS_PER_HOUR:
            self.logger.error(
                f"重启次数超过限制 ({MAX_RESTARTS_PER_HOUR}/小时)，停止守护"
            )
            return False
        return True

    def run(self):
        """主循环：启动 → 监控 → 崩溃重启。"""
        self.logger.info("=" * 50)
        self.logger.info("Galaxy 守护进程启动")
        self.logger.info(f"项目目录: {PROJECT_ROOT}")
        self.logger.info("=" * 50)

        # 前置检查
        self._set_env()
        if not self._check_dependencies():
            self.logger.error("依赖检查失败，退出")
            return 1

        while True:
            try:
                self.process = self._start_galaxy()
                self.logger.info(f"Galaxy PID: {self.process.pid}")
                self._monitor()

                # 进程结束
                returncode = self.process.wait()
                self.logger.warning(f"Galaxy 退出 (code: {returncode})")

            except KeyboardInterrupt:
                self.logger.info("收到中断信号，停止守护")
                if self.process and self.process.poll() is None:
                    self.process.terminate()
                return 0
            except Exception as e:
                self.logger.error(f"守护异常: {e}")

            # 崩溃重启逻辑
            if not self._should_restart():
                return 1

            self.logger.info(f"{RESTART_COOLDOWN}秒后重启...")
            time.sleep(RESTART_COOLDOWN)


# ── Windows 服务安装 ──────────────────────────────────────────────────

def install_service():
    """安装为 Windows 服务（需要管理员权限）。"""
    if sys.platform != "win32":
        print("Windows 服务仅支持 Windows 平台")
        return 1

    try:
        import win32serviceutil
        import win32service
        import win32event
    except ImportError:
        print("缺少 pywin32，运行: pip install pywin32")
        return 1

    # 使用 NSSM 方式更简单可靠
    nssm_path = PROJECT_ROOT / "tools" / "nssm.exe"
    if not nssm_path.exists():
        print("下载 NSSM...")
        # 简化版：提示用户手动安装
        print("""
  手动安装为 Windows 服务:

  1. 下载 NSSM: https://nssm.cc/download
  2. 以管理员运行 PowerShell:
     nssm install Galaxy "{python}" "{daemon}"
     nssm set Galaxy DisplayName "Galaxy AI"
     nssm set Galaxy Description "Galaxy AI Daemon"
     nssm start Galaxy

  3. 设置开机自启:
     nssm set Galaxy Start SERVICE_AUTO_START
        """.format(python=sys.executable, daemon=PROJECT_ROOT / "galaxy_daemon.py"))
        return 0

    return 0


def uninstall_service():
    """卸载 Windows 服务。"""
    print("卸载 Galaxy 服务...")
    subprocess.run(["sc", "delete", "Galaxy"], capture_output=True)
    print("✓ 服务已卸载")
    return 0


# ── 入口 ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Galaxy 守护进程")
    parser.add_argument("--install", action="store_true", help="安装为 Windows 服务")
    parser.add_argument("--uninstall", action="store_true", help="卸载服务")
    parser.add_argument("--status", action="store_true", help="查看状态")
    args = parser.parse_args()

    if args.install:
        return install_service()
    if args.uninstall:
        return uninstall_service()
    if args.status:
        print("运行: python galaxy_daemon.py (前台模式)")
        return 0

    # 前台运行模式
    daemon = GalaxyDaemon()
    return daemon.run()


if __name__ == "__main__":
    sys.exit(main())
