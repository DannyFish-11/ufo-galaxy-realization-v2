#!/usr/bin/env python3
"""
Galaxy Daemon — Crash-Restart Wrapper
======================================
Pure wrapper around main.py. Does NOT modify env vars or skip phases.
"""

import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.resolve()
LOG_DIR = PROJECT_ROOT / "logs"
MAX_LOG_DAYS = 7
MAX_RESTARTS_PER_HOUR = 5
RESTART_COOLDOWN = 60


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(exist_ok=True)
    cutoff = time.time() - MAX_LOG_DAYS * 86400
    for f in LOG_DIR.glob("galaxy_*.log"):
        if f.stat().st_mtime < cutoff:
            try:
                f.unlink()
            except OSError:
                pass
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


class GalaxyDaemon:
    def __init__(self):
        self.logger = setup_logging()
        self.process = None
        self.restart_count = 0
        self.restart_window_start = time.time()
        self._notifier = None  # lazy init

    def _notify(self, message: str, severity: str = "warning", category: str = "daemon") -> None:
        """Fire-and-forget notification (best-effort, non-blocking)."""
        try:
            import asyncio
            from galaxy_gateway.daemon_notifier import DaemonNotifier
            if self._notifier is None:
                self._notifier = DaemonNotifier()
            # Run async notify in a new task without blocking
            asyncio.get_running_loop().create_task(
                self._notifier.notify(message, severity=severity, category=category)
            )
        except Exception:
            self.logger.info("[NOTIFY] %s: %s", severity.upper(), message)

    def _start(self) -> subprocess.Popen:
        main_py = PROJECT_ROOT / "main.py"
        if not main_py.exists():
            raise FileNotFoundError(f"{main_py} not found")
        self.logger.info("Starting Galaxy (main.py)...")
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
        if self.process.stdout:
            for line in self.process.stdout:
                line = line.strip()
                if line:
                    self.logger.info(f"[Galaxy] {line[:200]}")

    def _should_restart(self) -> bool:
        now = time.time()
        if now - self.restart_window_start > 3600:
            self.restart_count = 0
            self.restart_window_start = now
        self.restart_count += 1
        if self.restart_count > MAX_RESTARTS_PER_HOUR:
            self.logger.error(f"Too many restarts ({MAX_RESTARTS_PER_HOUR}/hr), stopping")
            return False
        return True

    def run(self):
        self.logger.info("=" * 50)
        self.logger.info("Galaxy Daemon — main.py is the ONLY entrypoint")
        self.logger.info(f"Project: {PROJECT_ROOT}")
        self.logger.info("=" * 50)

        while True:
            try:
                self.process = self._start()
                self.logger.info(f"Galaxy PID: {self.process.pid}")
                self._monitor()
                code = self.process.wait()
                self.logger.warning(f"Galaxy exited (code: {code})")
                self._notify(
                    f"Galaxy 异常退出 (code {code})，第 {self.restart_count + 1} 次重启",
                    severity="warning",
                    category="crash_restart",
                )
            except KeyboardInterrupt:
                self.logger.info("Interrupted")
                if self.process and self.process.poll() is None:
                    self.process.terminate()
                return 0
            except Exception as e:
                self.logger.error(f"Daemon error: {e}")

            if not self._should_restart():
                self._notify(
                    f"Galaxy 连续重启超过 {MAX_RESTARTS_PER_HOUR} 次/小时，守护已停止",
                    severity="critical",
                    category="too_many_restarts",
                )
                return 1
            self.logger.info(f"Restarting in {RESTART_COOLDOWN}s...")
            time.sleep(RESTART_COOLDOWN)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true", help="Check daemon status")
    args = parser.parse_args()
    if args.status:
        print("Daemon runs in foreground. Use Ctrl+C to stop.")
        return 0
    return GalaxyDaemon().run()


if __name__ == "__main__":
    sys.exit(main())
