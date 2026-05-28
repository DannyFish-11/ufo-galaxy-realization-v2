"""
windows_service.watchdog -- Independent Watchdog Process
========================================================

If the Galaxy main process becomes unresponsive (no heartbeat for >60s),
the watchdog will kill and restart it.

Runs independently of the Galaxy process, so it works even if Python freezes.

Usage:
    python -m windows_service.watchdog start
    python -m windows_service.watchdog stop
"""

import os
import sys
import time
import signal
import subprocess
import logging
import argparse
from pathlib import Path

logger = logging.getLogger("Galaxy.Watchdog")

PID_FILE = Path.home() / ".galaxy" / "watchdog.pid"
GALAXY_PID_FILE = Path.home() / ".galaxy" / "galaxy.pid"
HEARTBEAT_FILE = Path.home() / ".galaxy" / "heartbeat"
TIMEOUT_SECONDS = 60  # 60 seconds without heartbeat = dead
CHECK_INTERVAL = 10   # Check every 10 seconds


def run_watchdog():
    """Watchdog main loop"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    logger.info("Watchdog started (timeout=%ds)", TIMEOUT_SECONDS)

    # Save watchdog PID
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))

    while True:
        time.sleep(CHECK_INTERVAL)

        # Check if Galaxy is running
        if not GALAXY_PID_FILE.exists():
            logger.warning("Galaxy PID file missing, restarting...")
            _restart_galaxy()
            continue

        # Check heartbeat
        if not HEARTBEAT_FILE.exists():
            logger.warning("Heartbeat file missing, restarting...")
            _restart_galaxy()
            continue

        try:
            last_beat = float(HEARTBEAT_FILE.read_text().strip() or 0)
            elapsed = time.time() - last_beat
        except (ValueError, OSError):
            logger.warning("Heartbeat file unreadable, restarting...")
            _restart_galaxy()
            continue

        if elapsed > TIMEOUT_SECONDS:
            logger.error(
                "Galaxy unresponsive for %.0fs, killing and restarting", elapsed
            )
            _kill_galaxy()
            time.sleep(2)
            _restart_galaxy()
        else:
            logger.debug("Heartbeat OK (%.0fs ago)", elapsed)


def _kill_galaxy():
    """Forcefully terminate Galaxy"""
    try:
        pid = int(GALAXY_PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGKILL)
        logger.info("Killed Galaxy process %d", pid)
    except (OSError, ValueError) as exc:
        logger.warning("Failed to kill Galaxy: %s", exc)


def _restart_galaxy():
    """Restart Galaxy"""
    project_root = Path(__file__).parent.parent
    main_script = project_root / "main.py"

    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root)
    env["USE_LOCAL_BRAIN_FIRST"] = "true"

    proc = subprocess.Popen(
        [sys.executable, "-m", "main", "--gpu-opt", "--persistent-models", "all"],
        cwd=project_root,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    GALAXY_PID_FILE.write_text(str(proc.pid))
    logger.info("Galaxy restarted with PID %d", proc.pid)


def update_heartbeat():
    """Called periodically by the Galaxy main process to update heartbeat timestamp"""
    HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT_FILE.write_text(str(time.time()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["start", "stop", "heartbeat"])
    args = parser.parse_args()

    if args.command == "start":
        run_watchdog()
    elif args.command == "stop":
        if PID_FILE.exists():
            try:
                pid = int(PID_FILE.read_text().strip())
                os.kill(pid, signal.SIGTERM)
            except (OSError, ValueError):
                pass
            PID_FILE.unlink(missing_ok=True)
            print("Watchdog stopped")
    elif args.command == "heartbeat":
        update_heartbeat()
        print("Heartbeat updated")
