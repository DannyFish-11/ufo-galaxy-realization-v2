#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.legacy_purge_registry
===========================

PR-10 — Final Legacy Purge and Baseline Hardening.

Authoritative catalogue of every legacy purge and permanent isolation
decision made as part of the 10-PR cleanup/hardening sequence.  This
module is the single machine-readable reference for:

- What was purged or hard-disabled, and when.
- What was permanently isolated into an archive/legacy location.
- What compatibility wrappers remain and their strict constraints.
- What residual ambiguities have been resolved.

**Design contract**
--------------------
This module is read-only metadata.  It does **not** alter runtime
behaviour; it is used by:

- ``scripts/validate_runtime.py`` — to verify purge decisions are in
  effect.
- ``tests/test_pr10_legacy_purge_hardening.py`` — to assert the
  registry is coherent and complete.
- Human maintainers — as the authoritative purge audit log.

Usage::

    from core.legacy_purge_registry import (
        PURGE_REGISTRY,
        PurgeDecision,
        PurgeStatus,
        get_purge_entry,
        get_entries_by_status,
    )

    for entry in PURGE_REGISTRY:
        print(entry.asset_path, entry.status.value)
"""

from __future__ import annotations

import dataclasses
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

__all__ = [
    "PurgeStatus",
    "PurgeDecision",
    "PURGE_REGISTRY",
    "get_purge_entry",
    "get_entries_by_status",
    "get_entries_by_pr",
    "purge_registry_summary",
]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PurgeStatus(str, Enum):
    """Final disposition status of a legacy asset.

    ``HARD_DISABLED``
        Module still exists on disk but raises ``RuntimeError`` on import
        and emits ``DeprecationWarning``.  Kept only to give callers a
        clear error message rather than an obscure ``ImportError``.

    ``PERMANENTLY_ISOLATED``
        Asset moved into a non-active location (e.g. ``_legacy/``,
        ``archive/``) and explicitly excluded from active runtime
        discovery.

    ``DEAD_REFERENCE_REMOVED``
        A call-site or reference that pointed at a hard-disabled or
        non-existent target has been deleted, closing the dead code path.

    ``WRAPPER_HARDENED``
        A legacy compatibility wrapper that still exists for backward
        compatibility but whose ability to introduce new logic has been
        hardened (guarded by comments, docs, and/or tests).

    ``LEGACY_MARKER_ADDED``
        Asset still exists but is unambiguously labelled as legacy/demoted
        via a marker file (``LEGACY_SURFACE.md``) or inline annotation so
        there is no risk of it being mistaken for an active surface.
    """

    HARD_DISABLED = "hard_disabled"
    PERMANENTLY_ISOLATED = "permanently_isolated"
    DEAD_REFERENCE_REMOVED = "dead_reference_removed"
    WRAPPER_HARDENED = "wrapper_hardened"
    LEGACY_MARKER_ADDED = "legacy_marker_added"


# ---------------------------------------------------------------------------
# PurgeDecision dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class PurgeDecision:
    """Single purge/isolation decision record.

    Attributes
    ----------
    asset_path:
        Repository-relative path of the asset (file, directory, or
        function) affected by this decision.
    status:
        Final disposition (:class:`PurgeStatus`).
    pr:
        The PR in the 10-PR sequence that made this decision (e.g.
        ``"PR-3"``, ``"PR-10"``).
    rationale:
        Human-readable explanation of why this decision was taken.
    canonical_replacement:
        Optional pointer to the active/canonical replacement that
        callers should use instead.  ``None`` if no replacement exists
        (the feature was simply retired).
    """

    asset_path: str
    status: PurgeStatus
    pr: str
    rationale: str
    canonical_replacement: Optional[str] = None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

#: Complete ordered registry of all legacy purge / isolation decisions.
PURGE_REGISTRY: Tuple[PurgeDecision, ...] = (
    # ── PR-3: Legacy Windows client stack retired ──────────────────────────

    PurgeDecision(
        asset_path="windows_client/client.py",
        status=PurgeStatus.HARD_DISABLED,
        pr="PR-3",
        rationale=(
            "Legacy bespoke Gateway/AIP client.  The canonical Windows "
            "ingress path is windows_aip_client.py → "
            "WindowsExecutionArbiter.route_command()."
        ),
        canonical_replacement="windows_client/windows_aip_client.py",
    ),
    PurgeDecision(
        asset_path="windows_client/ui_sidebar.py",
        status=PurgeStatus.HARD_DISABLED,
        pr="PR-3",
        rationale=(
            "Legacy Tk chat sidebar.  The canonical desktop status surface "
            "is windows_client/status_board_v2/ (projection-driven)."
        ),
        canonical_replacement="windows_client/status_board_v2/",
    ),
    PurgeDecision(
        asset_path="windows_client/desktop_automation.py",
        status=PurgeStatus.HARD_DISABLED,
        pr="PR-3",
        rationale=(
            "Legacy pyautogui automation path.  The active automation layer "
            "is windows_client/autonomy/."
        ),
        canonical_replacement="windows_client/autonomy/",
    ),
    PurgeDecision(
        asset_path="windows_client/windows_mcp_server.py",
        status=PurgeStatus.HARD_DISABLED,
        pr="PR-3",
        rationale=(
            "Legacy MCP stdio execution path.  MCP serving is handled by "
            "the galaxy_gateway substrate."
        ),
        canonical_replacement="galaxy_gateway/",
    ),
    PurgeDecision(
        asset_path="windows_client/main.py",
        status=PurgeStatus.HARD_DISABLED,
        pr="PR-3",
        rationale=(
            "Legacy F12-hotkey chat/sidebar client entrypoint.  "
            "Active runtime direction: DesktopPresenceRuntime + "
            "windows_client/status_board_v2/."
        ),
        canonical_replacement="core/desktop_presence_runtime.py",
    ),
    PurgeDecision(
        asset_path="windows_client/windows_client_integrated.py",
        status=PurgeStatus.HARD_DISABLED,
        pr="PR-3",
        rationale="Legacy PyQt6 integrated client.  Superseded by status_board_v2.",
        canonical_replacement="windows_client/status_board_v2/",
    ),
    PurgeDecision(
        asset_path="windows_client/key_listener.py",
        status=PurgeStatus.HARD_DISABLED,
        pr="PR-3",
        rationale=(
            "Legacy F12 hotkey listener.  No canonical hotkey path in the "
            "active architecture."
        ),
    ),
    PurgeDecision(
        asset_path="enhancements/clients/windows_client/run_ui.py",
        status=PurgeStatus.HARD_DISABLED,
        pr="PR-3",
        rationale=(
            "Enhancement launcher that targeted windows_client/main.py "
            "(the retired F12-hotkey sidebar client).  Hard-disabled to "
            "prevent accidental resurrection of the legacy desktop launch "
            "path."
        ),
        canonical_replacement=(
            "python unified_launcher.py  "
            "(or python main.py on Windows: start.bat)"
        ),
    ),
    PurgeDecision(
        asset_path="windows_client/_legacy/",
        status=PurgeStatus.PERMANENTLY_ISOLATED,
        pr="PR-3",
        rationale=(
            "Legacy launchers and UI assets moved into _legacy/ subdirectory "
            "to make the isolation boundary explicit and filesystem-visible."
        ),
    ),

    # ── PR-4: dashboard/frontend demoted ─────────────────────────────────

    PurgeDecision(
        asset_path="dashboard/",
        status=PurgeStatus.LEGACY_MARKER_ADDED,
        pr="PR-4",
        rationale=(
            "dashboard/ was previously the primary WebUI management panel. "
            "Demoted to LEGACY_SURFACE.  Marked with dashboard/LEGACY_SURFACE.md "
            "and dashboard/frontend/LEGACY_SURFACE.md.  New management API lives "
            "in core/api_routes.py."
        ),
        canonical_replacement="core/api_routes.py",
    ),

    # ── PR-10: Final legacy purge — dead reference in start_galaxy.py ─────

    PurgeDecision(
        asset_path="start_galaxy.py::_start_desktop()",
        status=PurgeStatus.DEAD_REFERENCE_REMOVED,
        pr="PR-10",
        rationale=(
            "_start_desktop() called os.system() with a path to "
            "enhancements/clients/windows_client/run_ui.py, which has been "
            "hard-disabled since PR-3.  The function created a false impression "
            "that --desktop / --all flags launched a live desktop UI.  "
            "Removed in PR-10 final purge; --desktop/--all flags now emit a "
            "DeprecationWarning and do NOT start any UI."
        ),
        canonical_replacement=(
            "windows_client/status_board_v2/  "
            "(canonical read-only desktop status board, projection-driven)"
        ),
    ),
    PurgeDecision(
        asset_path="start_galaxy.py",
        status=PurgeStatus.WRAPPER_HARDENED,
        pr="PR-10",
        rationale=(
            "start_galaxy.py is a legacy compatibility wrapper that must not "
            "grow new startup logic.  PR-10 hardened it by: removing the dead "
            "_start_desktop() function, adding the PR-10 LEGACY WRAPPER comment "
            "guard, updating the deprecation message to reference the purge, "
            "and keeping --desktop/--all as no-op stubs with clear warnings."
        ),
        canonical_replacement="python unified_launcher.py  (or python main.py)",
    ),
    PurgeDecision(
        asset_path="start_l4.py",
        status=PurgeStatus.WRAPPER_HARDENED,
        pr="PR-10",
        rationale=(
            "start_l4.py has been frozen since PR-6 (delegates to "
            "unified_launcher.py).  PR-10 confirms it carries the required "
            "DeprecationWarning and that no new L4 logic has been added.  "
            "It must not be extended."
        ),
        canonical_replacement="python unified_launcher.py  (or python main.py)",
    ),

    # ── PR-S6: Finalize server-side legacy demotion ────────────────────────

    PurgeDecision(
        asset_path="galaxy_gateway/task_router.py::TaskRouter",
        status=PurgeStatus.WRAPPER_HARDENED,
        pr="PR-S6",
        rationale=(
            "TaskRouter is a legacy gateway-level HTTP task dispatcher that sends "
            "tasks directly to devices, bypassing the canonical "
            "TaskEnvelope / DeviceRouter chain and core.cross_device_execution_chain.  "
            "PR-S6 adds a LEGACY PATH GUARDRAIL in TaskRouter.__init__, a deprecation "
            "docstring, and registers the path in LEGACY_PATH_REGISTRY.  "
            "TaskRouter is retained as a compatibility shim only; it must not be "
            "extended with new execution logic."
        ),
        canonical_replacement=(
            "core.e2e_orchestrator.process_user_input()  "
            "or galaxy_gateway.device_router.DeviceRouter.route_task()"
        ),
    ),
    PurgeDecision(
        asset_path="galaxy_gateway/task_router.py::TaskScheduler",
        status=PurgeStatus.WRAPPER_HARDENED,
        pr="PR-S6",
        rationale=(
            "TaskScheduler is a legacy gateway-level task planner bundled inside "
            "TaskRouter.  It performs topological-sort scheduling that predates "
            "core.task_graph.  PR-S6 adds a LEGACY PATH GUARDRAIL in "
            "TaskScheduler.__init__, a deprecation docstring, and registers the path "
            "in LEGACY_PATH_REGISTRY.  Do not instantiate directly from new code."
        ),
        canonical_replacement=(
            "OpenClawd → CommandRouter → TaskEnvelope → DeviceRouter  "
            "(canonical server-side execution planning pipeline)"
        ),
    ),
    PurgeDecision(
        asset_path="galaxy_gateway/handlers/message_handler.py::MessageHandler",
        status=PurgeStatus.WRAPPER_HARDENED,
        pr="PR-S6",
        rationale=(
            "MessageHandler is the chain-B ingress handler (chain B: "
            "MessageHandler → TaskOrchestrator).  The dual-entry architecture "
            "(chain A canonical + chain B legacy) was identified in PR-S5; this "
            "PR-S6 decision makes the chain-B ingress boundary explicit.  "
            "PR-S6 adds a LEGACY PATH GUARDRAIL in MessageHandler.__init__, a "
            "deprecation docstring, and registers the path in LEGACY_PATH_REGISTRY.  "
            "MessageHandler carries no independent runtime authority and must not be "
            "extended with new execution or dispatch logic."
        ),
        canonical_replacement=(
            "Chain A: galaxy_gateway.websocket_handler → "
            "galaxy_gateway.device_router.DeviceRouter  "
            "(canonical server-side ingress pipeline)"
        ),
    ),
)

# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def get_purge_entry(asset_path: str) -> Optional[PurgeDecision]:
    """Return the :class:`PurgeDecision` for *asset_path*, or ``None``.

    The match is performed by exact string equality on
    :attr:`PurgeDecision.asset_path`.
    """
    for entry in PURGE_REGISTRY:
        if entry.asset_path == asset_path:
            return entry
    return None


def get_entries_by_status(status: PurgeStatus) -> List[PurgeDecision]:
    """Return all entries with the given *status*."""
    return [e for e in PURGE_REGISTRY if e.status == status]


def get_entries_by_pr(pr: str) -> List[PurgeDecision]:
    """Return all entries attributed to *pr* (e.g. ``"PR-10"``)."""
    return [e for e in PURGE_REGISTRY if e.pr == pr]


def purge_registry_summary() -> Dict[str, object]:
    """Return a summary dict suitable for logging or JSON serialization."""
    by_status: Dict[str, List[str]] = {s.value: [] for s in PurgeStatus}
    by_pr: Dict[str, List[str]] = {}
    for entry in PURGE_REGISTRY:
        by_status[entry.status.value].append(entry.asset_path)
        by_pr.setdefault(entry.pr, []).append(entry.asset_path)
    return {
        "total_entries": len(PURGE_REGISTRY),
        "by_status": {k: v for k, v in by_status.items() if v},
        "by_pr": by_pr,
    }
