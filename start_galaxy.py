#!/usr/bin/env python3
"""
Galaxy — Quick Start (compatibility wrapper)
=============================================

.. deprecated::
    This script is a **compatibility wrapper** that delegates all work to
    ``unified_launcher.py``.  It exists only for backward compatibility with
    existing scripts that call ``start_galaxy.py``.

    **PR-10 (Final Legacy Purge):** The ``--desktop`` / ``--all`` flags and
    the ``_start_desktop()`` helper that previously pointed at the retired
    ``enhancements/clients/windows_client/run_ui.py`` stub have been removed.
    That launcher targeted the legacy F12-hotkey chat/sidebar client which has
    been hard-disabled since PR-3.  Accepting those flags silently made the
    wrapper appear to support a live desktop launch path when it did not.

    Migration::

        # Legacy (compatibility wrapper — still delegates to unified_launcher):
        python start_galaxy.py [--port PORT]

        # Preferred (full system, all subsystems, port 9000):
        python unified_launcher.py [--no-l4] [--no-ui] [--port PORT]
        # or the canonical OS-level entry:
        python main.py [--no-l4] [--no-ui]

    Active Windows direction (not via start_galaxy.py):
        core/desktop_presence_runtime.py  (DesktopPresenceRuntime tri-state shell)
        windows_client/status_board_v2/   (projection-driven desktop status board)

    See docs/MAINTAINER_RUNBOOK.md for the authoritative reference.
"""
# PR-10 LEGACY WRAPPER — do not add new startup logic here.
# All startup functionality belongs in launcher/ (see docs/MAINTAINER_RUNBOOK.md).

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


def main():
    warnings.warn(
        "start_galaxy.py is a legacy compatibility wrapper (PR-10 hardened). "
        "Use 'python unified_launcher.py' (or 'python main.py') as the primary entry point. "
        "The legacy dashboard surfaces have been demoted (PR-4/PR-8). "
        "The --desktop/--all flags have been removed: the retired run_ui.py launcher "
        "they targeted is hard-disabled. "
        "Active Windows direction: DesktopPresenceRuntime + windows_client/status_board_v2/. "
        "See docs/MAINTAINER_RUNBOOK.md.",
        DeprecationWarning,
        stacklevel=1,
    )
    logger.warning(
        "⚠  LEGACY WRAPPER (PR-10): start_galaxy.py delegates to unified_launcher.py. "
        "Use 'python unified_launcher.py' directly. "
        "Legacy dashboard surfaces have been demoted (PR-8/PR-4). "
        "Current runtime direction: DesktopPresenceRuntime + status_board_v2."
    )

    import argparse
    parser = argparse.ArgumentParser(
        description="Galaxy Quick Start (legacy wrapper → unified_launcher.py)"
    )
    parser.add_argument("--port", type=int, default=9000, help="API service port (default: 9000)")
    # Accept (and ignore) any extra unified_launcher flags so existing scripts don't break
    parser.add_argument("--no-l4", action="store_true", help="Pass through to unified_launcher")
    parser.add_argument("--no-nodes", action="store_true", help="Pass through to unified_launcher")
    parser.add_argument("--no-ui", action="store_true", help="Pass through to unified_launcher")
    parser.add_argument("--minimal", "-m", action="store_true",
                        help="Pass through to unified_launcher")
    # --desktop and --all are accepted but produce a clear deprecation notice
    # rather than silently doing nothing or failing; they do NOT start any UI.
    parser.add_argument(
        "--desktop",
        action="store_true",
        help=(
            "[REMOVED] The legacy --desktop path (run_ui.py) has been retired (PR-10). "
            "Active Windows direction: windows_client/status_board_v2/."
        ),
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="[REMOVED — same as --desktop] Legacy --all flag; no longer starts a desktop UI.",
    )
    args = parser.parse_args()

    if args.desktop or args.all:
        warnings.warn(
            "start_galaxy.py --desktop / --all: the legacy desktop launch path "
            "(enhancements/clients/windows_client/run_ui.py) has been permanently retired "
            "(PR-10 final purge). The flag is accepted for backward compatibility but "
            "does NOT start a desktop UI. "
            "Active Windows direction: windows_client/status_board_v2/. "
            "See docs/MAINTAINER_RUNBOOK.md.",
            DeprecationWarning,
            stacklevel=1,
        )
        logger.warning(
            "⚠  --desktop/--all flag ignored (PR-10): the legacy run_ui.py launcher has been "
            "permanently retired. Active Windows: windows_client/status_board_v2/."
        )

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

    # Delegate to unified_launcher — the sole startup authority.
    sys.argv = [sys.argv[0]] + fwd_args
    from unified_launcher import main as unified_main
    unified_main()


if __name__ == "__main__":
    main()
