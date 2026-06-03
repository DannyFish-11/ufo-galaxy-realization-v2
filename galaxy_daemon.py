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
        # M1 fixed: track restart timestamps in a list for accurate rate limiting
        self._restart_timestamps: list = []
        self._notifier = None  # lazy init

    def _notify(self, message: str, severity: str = "warning", category: str = "daemon") -> None:
        """Fire-and-forget notification using a dedicated thread event loop."""
        try:
            import threading
            def _send():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    from galaxy_gateway.daemon_notifier import DaemonNotifier
                    notifier = DaemonNotifier()
                    loop.run_until_complete(notifier.notify(message, severity=severity, category=category))
                finally:
                    loop.close()
            threading.Thread(target=_send, daemon=True).start()
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
        """Non-blocking pipe read with drain on exit."""
        import selectors
        if not self.process or not self.process.stdout:
            return
        sel = selectors.DefaultSelector()
        sel.register(self.process.stdout, selectors.EVENT_READ)
        try:
            while True:
                # Check if process exited
                ret = self.process.poll()
                if ret is not None:
                    break
                events = sel.select(timeout=1.0)
                for key, _ in events:
                    line = key.fileobj.readline()
                    if line:
                        self.logger.info("[Galaxy] %s", line[:200].strip())
                    else:
                        break
        finally:
            sel.close()
            if self.process.stdout:
                self.process.stdout.close()

    def _should_restart(self) -> bool:
        # M1 fixed: use timestamp list for accurate restart rate limiting
        now = time.time()
        window_start = now - 3600
        # Keep only timestamps within the last hour
        self._restart_timestamps = [ts for ts in self._restart_timestamps if ts > window_start]
        self._restart_timestamps.append(now)
        if len(self._restart_timestamps) > MAX_RESTARTS_PER_HOUR:
            self.logger.error("Too many restarts (%d/hr), stopping", MAX_RESTARTS_PER_HOUR)
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
                    f"Galaxy 连续重启超过 {MAX_RES