#!/usr/bin/env python3
"""
UFO Galaxy — Quick Start (Dashboard / WebUI)
=============================================

Lightweight launcher for the Dashboard web UI.
For full system launch, use unified_launcher.py or deploy.sh.

Usage:
    python start_galaxy.py              # Dashboard on :8080
    python start_galaxy.py --port 9000  # Custom port
    python start_galaxy.py --desktop    # Windows desktop UI
    python start_galaxy.py --all        # Dashboard + Desktop
"""

import os
import sys
import asyncio
import argparse
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("Galaxy")


def check_dependencies():
    """Check that minimal dependencies are installed."""
    required = ['fastapi', 'uvicorn', 'httpx', 'pydantic']
    missing = []
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        logger.error(f"Missing dependencies: {missing}")
        logger.info("Install: pip install " + " ".join(missing))
        return False
    return True


def print_banner():
    """Print startup banner."""
    try:
        from core.ascii_art import GALAXY_ASCII_MINIMAL
        print(GALAXY_ASCII_MINIMAL)
    except ImportError:
        print("=" * 50)
        print("  UFO Galaxy — L4 Autonomous Intelligence System")
        print("=" * 50)
    print()


def init_system():
    """Initialize core subsystems."""
    logger.info("Initializing system...")
    try:
        from core.unified_config import config
        logger.info(f"Config loaded: {len(config.get_all())} entries")
    except Exception:
        logger.warning("unified_config not available, using defaults")

    try:
        from core.device_registry import device_registry
        logger.info("Device registry ready")
    except Exception:
        pass

    try:
        from core.device_communication import device_comm
        logger.info("Device communication ready")
    except Exception:
        pass

    return True


def start_dashboard(port: int = 8080):
    """Start Dashboard web UI."""
    import uvicorn
    logger.info(f"Starting Dashboard on http://0.0.0.0:{port}")

    try:
        from dashboard.backend.main import app
    except ImportError:
        logger.error("dashboard.backend.main not found")
        sys.exit(1)

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


def start_desktop():
    """Start Windows desktop UI."""
    if sys.platform != "win32":
        logger.warning("Desktop UI is currently Windows-only")
        return
    os.system(f"python {PROJECT_ROOT}/enhancements/clients/windows_client/run_ui.py")


def main():
    parser = argparse.ArgumentParser(description='UFO Galaxy Quick Start')
    parser.add_argument('--desktop', action='store_true', help='Launch desktop UI')
    parser.add_argument('--all', action='store_true', help='Launch Dashboard + desktop')
    parser.add_argument('--port', type=int, default=8080, help='Dashboard port (default: 8080)')
    args = parser.parse_args()

    print_banner()

    if not check_dependencies():
        sys.exit(1)

    init_system()

    logger.info("System ready")
    print()

    if args.all:
        import multiprocessing
        p1 = multiprocessing.Process(target=start_dashboard, args=(args.port,))
        p2 = multiprocessing.Process(target=start_desktop)
        p1.start()
        p2.start()
        p1.join()
        p2.join()
    elif args.desktop:
        start_desktop()
    else:
        start_dashboard(args.port)


if __name__ == "__main__":
    main()
