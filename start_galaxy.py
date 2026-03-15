#!/usr/bin/env python3
"""
Galaxy — Quick Start (compatibility wrapper)
=============================================

.. deprecated::
    This script is a **compatibility wrapper** that delegates all work to
    ``unified_launcher.py``.  The two dashboard instances (previously on port
    8080 and 8085) have been merged.  Everything now runs on port **9000**
    through the single unified entry point.

    Migration::

        # Legacy (kept for backward compatibility — redirects to unified_launcher):
        python start_galaxy.py [--port PORT] [--desktop] [--all]

        # Preferred (full system, all subsystems, port 9000):
        python unified_launcher.py [--no-l4] [--no-ui] [--port PORT]
        # or the delegating wrapper:
        python main.py [--no-l4] [--no-ui]

All flags understood by this script are translated to their unified_launcher
equivalents and passed through.  The ``--desktop`` flag still launches the
Windows desktop UI after unified_launcher hands off control.
"""

import os
import sys
import logging
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("Galaxy")


def _start_desktop():
    """Launch the Windows desktop UI (Windows-only)."""
    if sys.platform != "win32":
        logger.warning("Desktop UI is currently Windows-only")
        return
    os.system(f"python {PROJECT_ROOT}/enhancements/clients/windows_client/run_ui.py")


def main():
    warnings.warn(
        "start_galaxy.py is a compatibility wrapper. "
        "Use 'python unified_launcher.py' (or 'python main.py') as the primary entry point. "
        "Both dashboards have been merged to port 9000.",
        DeprecationWarning,
        stacklevel=1,
    )
    logger.warning(
        "⚠  COMPATIBILITY WRAPPER: start_galaxy.py delegates to unified_launcher.py. "
        "Use 'python unified_launcher.py' directly. All services run on port 9000."
    )

    import argparse
    parser = argparse.ArgumentParser(
        description="Galaxy Quick Start (compatibility wrapper → unified_launcher.py)"
    )
    parser.add_argument("--desktop", action="store_true", help="Also launch Windows desktop UI")
    parser.add_argument("--all", action="store_true", help="Dashboard + desktop UI")
    parser.add_argument("--port", type=int, default=9000, help="Dashboard port (default: 9000)")
    # Accept (and ignore) any extra unified_launcher flags so existing scripts don't break
    parser.add_argument("--no-l4", action="store_true", help="Pass through to unified_launcher")
    parser.add_argument("--no-nodes", action="store_true", help="Pass through to unified_launcher")
    parser.add_argument("--no-ui", action="store_true", help="Pass through to unified_launcher")
    parser.add_argument("--minimal", "-m", action="store_true",
                        help="Pass through to unified_launcher")
    args = parser.parse_args()

    # Build the forwarded argv for unified_launcher
    fwd_args = ["--port", str(args.port)]
    if getattr(args, "no_l4", False):
        fwd_args.append("--no-l4")
    if getattr(args, "no_nodes", False):
        fwd_args.append("--no-nodes")
    if getattr(args, "no_ui", False):
        fwd_args.append("--no-ui")
    if getattr(args, "minimal", False):
        fwd_args.append("--minimal")

    # Optionally start desktop UI in a background process before handing over
    if args.desktop or args.all:
        import multiprocessing
        desktop_proc = multiprocessing.Process(target=_start_desktop)
        desktop_proc.start()

    # Delegate to unified_launcher
    sys.argv = [sys.argv[0]] + fwd_args
    from unified_launcher import main as unified_main
    unified_main()


if __name__ == "__main__":
    main()
