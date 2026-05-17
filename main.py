#!/usr/bin/env python3
"""
Galaxy-Nexus 星枢 — System Orchestrator
========================================

**SYSTEM_ORCHESTRATOR_AUTHORITY** — ``main.py:SYSTEM_ORCHESTRATOR``
--------------------------------------------------------------------
This file is the **canonical system orchestrator** for Galaxy-Nexus.
``python main.py`` is the official startup path.

Staged bring-up contract (PR-2)
--------------------------------
.. code-block:: text

    Phase 1 — LOAD_CONFIG           Load unified configuration baseline
    Phase 2 — RESOLVE_MODE          Resolve current system mode
    Phase 3 — ENV_CHECKS            Environment / bootstrap checks
    Phase 4 — BACKGROUND_SUBSYSTEMS Background subsystem bring-up hooks
    Phase 5 — RUNTIME_SUBJECT       Runtime subject bring-up hooks
    Phase 6 — DESKTOP_SURFACE       Desktop surface bring-up hooks
    Phase 7 — READINESS_SUMMARY     Final readiness summary

``unified_launcher.py`` is a **subordinate** launcher component invoked during
Phase 4–6.  It is NOT a competing top-level startup authority.

Subject lifecycle authority
---------------------------
- :class:`~core.desktop_presence_runtime.DesktopPresenceRuntime` — outer shell
- :class:`~core.openclawd.OpenClawd` — subject core

Usage
-----
    python main.py              # Start complete Galaxy-Nexus system
    python main.py --setup      # Run configuration wizard
    python main.py --status     # Show system status
    python main.py --help       # Show all startup options

All startup options are forwarded to ``unified_launcher.py`` (subordinate
component) after the orchestrator completes its staged pre-flight sequence.
"""

import os
import sys
import subprocess
import logging
from pathlib import Path

from entrypoint_role_contract import (
    EntrypointRole,
    MAIN_ENTRY_ID,
    assert_single_unique_main_entrypoint,
    ensure_entrypoint_role,
)

# ---------------------------------------------------------------------------
# Bootstrap: project root + sys.path
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("Galaxy")

# ---------------------------------------------------------------------------
# Authority declaration — referenced by validate_runtime.py and CI guardrails
# ---------------------------------------------------------------------------

SYSTEM_ORCHESTRATOR_AUTHORITY: str = (
    "main.py:SYSTEM_ORCHESTRATOR — canonical staged bring-up contract (PR-2)"
)


# ---------------------------------------------------------------------------
# Orchestrator bring-up sequence
# ---------------------------------------------------------------------------

def _is_strict_preflight() -> bool:
    """Return True when GALAXY_STRICT_PREFLIGHT is set to a truthy value.

    Set ``GALAXY_STRICT_PREFLIGHT=1`` (or ``true``) to make **any** preflight
    exception or Phase-3 CRITICAL failure abort startup rather than proceeding
    in degraded mode.  Useful for production deployments and CI pipelines
    where silent-success startup is unacceptable.
    """
    return os.environ.get("GALAXY_STRICT_PREFLIGHT", "").lower() in ("1", "true", "yes")


def _run_orchestrator_preflight() -> bool:
    """Execute the staged pre-flight bring-up sequence (Phases 1–7).

    Returns ``True`` if the system is ready to proceed to the full async
    bring-up via ``unified_launcher``, ``False`` on hard failure.

    Logs one line per phase so startup logs reflect clear staged bring-up.

    Strict mode
    ~~~~~~~~~~~
    When ``GALAXY_STRICT_PREFLIGHT=1`` any exception raised by the orchestrator
    itself is treated as a hard failure (returns ``False``) rather than being
    silently swallowed.  This prevents critically broken environments from
    appearing healthy at startup.
    """
    strict = _is_strict_preflight()
    try:
        from core.system_orchestrator import SystemOrchestrator
        orch = SystemOrchestrator(continue_on_failure=False, strict_preflight=strict)
        summary = orch.run_startup_sequence()
        logger.info("Orchestrator bring-up complete:\n%s", summary)
        return summary.is_ready()
    except Exception as exc:
        if strict:
            logger.error(
                "Orchestrator pre-flight raised an exception "
                "(GALAXY_STRICT_PREFLIGHT=1 — treating as hard failure): %s",
                exc,
            )
            return False
        logger.warning(
            "Orchestrator pre-flight raised an exception (non-fatal): %s", exc
        )
        # Degraded but non-fatal — proceed with bring-up
        return True


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------

def main() -> int:
    """Canonical system orchestrator entry-point.

    Execution order
    ~~~~~~~~~~~~~~~
    1. ``--setup`` shortcut — bypass bring-up and launch config wizard.
    2. Run staged orchestrator pre-flight (Phases 1–7).
    3. If pre-flight fails hard, exit immediately.
    4. Otherwise, hand off to ``unified_launcher.py`` (subordinate component)
       which performs the full async bring-up of all services and the runtime
       subject.
    """

    single_main_ok = assert_single_unique_main_entrypoint()
    main_role_ok = ensure_entrypoint_role(MAIN_ENTRY_ID, EntrypointRole.UNIQUE_MAIN)
    if not single_main_ok:
        logger.error("Entrypoint role contract violation: single unique main entrypoint is broken.")
        return 1
    if not main_role_ok:
        logger.error("Entrypoint role contract violation: main.py does not have UNIQUE_MAIN role.")
        return 1

    # --setup: shortcut to configuration wizard (bypasses bring-up)
    if "--setup" in sys.argv:
        wizard_path = PROJECT_ROOT / "setup_wizard.py"
        if wizard_path.exists():
            return subprocess.call([sys.executable, str(wizard_path)])
        logger.error("Configuration wizard not found: %s", wizard_path)
        return 1

    logger.info("Galaxy-Nexus starting — %s", SYSTEM_ORCHESTRATOR_AUTHORITY)

    # Phases 1–7: staged orchestrator pre-flight
    ready = _run_orchestrator_preflight()
    if not ready:
        logger.error(
            "Orchestrator pre-flight failed — system cannot start. "
            "Check logs above for details."
        )
        return 1

    # Hand off to the subordinate launcher for full async bring-up
    launcher_path = PROJECT_ROOT / "unified_launcher.py"
    if not launcher_path.exists():
        logger.error(
            "Subordinate launcher not found: %s\n"
            "Ensure unified_launcher.py is present in the project root.",
            launcher_path,
        )
        return 1

    args = [sys.executable, str(launcher_path)] + sys.argv[1:]
    try:
        return subprocess.call(args)
    except KeyboardInterrupt:
        logger.info("Interrupt received — exiting.")
        return 0
    except Exception as exc:
        logger.error("Startup failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
