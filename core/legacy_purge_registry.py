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
        status=PurgeStatus.PERMANENTLY_ISOLATED,
        pr="PR-10",
        rationale=(
            "start_galaxy.py was a legacy compatibility wrapper that delegated "
            "to unified_launcher.py.  PR-10 hardened it; the post-PR-10 cleanup "
            "fully removes it.  There is no use case for the wrapper now that "
            "unified_launcher.py is the sole startup authority.  The file has been "
            "deleted from the repository.  Use 'python main.py' or "
            "'python unified_launcher.py' directly."
        ),
        canonical_replacement="python unified_launcher.py  (or python main.py)",
    ),
    PurgeDecision(
        asset_path="start_l4.py",
        status=PurgeStatus.PERMANENTLY_ISOLATED,
        pr="PR-10",
        rationale=(
            "start_l4.py was frozen since PR-6 (delegates to unified_launcher.py). "
            "The post-PR-10 cleanup fully removes it.  There is no use case for "
            "the wrapper now that unified_launcher.py manages L4 lifecycle.  "
            "The file has been deleted from the repository.  Use 'python main.py' "
            "or 'python unified_launcher.py' directly."
        ),
        canonical_replacement="python unified_launcher.py  (or python main.py)",
    ),

    # ── PR-S6: Final server-side legacy demotion ──────────────────────────

    PurgeDecision(
        asset_path="galaxy_gateway/task_router.py::TaskScheduler",
        status=PurgeStatus.WRAPPER_HARDENED,
        pr="PR-S6",
        rationale=(
            "TaskScheduler is a legacy topological scheduler that builds "
            "ExecutionPlan objects outside the canonical TaskGraph pipeline.  "
            "PR-S6 adds a deprecation docstring, a LEGACY PATH GUARDRAIL in "
            "__init__, and a LEGACY_PATH_REGISTRY entry.  The class is retained "
            "for backward compatibility; new scheduling must use core.task_graph."
        ),
        canonical_replacement="core/task_graph.py  (core.task_graph.TaskGraph)",
    ),
    PurgeDecision(
        asset_path="galaxy_gateway/task_router.py::TaskRouter",
        status=PurgeStatus.WRAPPER_HARDENED,
        pr="PR-S6",
        rationale=(
            "TaskRouter is a legacy raw-HTTP dispatch loop that routes tasks "
            "to devices bypassing DeviceRouter / TaskEnvelope / cross-device "
            "chain.  PR-S6 adds a deprecation docstring, a LEGACY PATH GUARDRAIL "
            "in __init__, and a LEGACY_PATH_REGISTRY entry.  The class is retained "
            "for backward compatibility; new dispatch must use DeviceRouter.route_task."
        ),
        canonical_replacement=(
            "galaxy_gateway/device_router.py  (DeviceRouter.route_task)  "
            "or  core/e2e_orchestrator.py  (process_user_input)"
        ),
    ),
    PurgeDecision(
        asset_path="galaxy_gateway/handlers/message_handler.py::MessageHandler",
        status=PurgeStatus.WRAPPER_HARDENED,
        pr="PR-S6",
        rationale=(
            "MessageHandler is the legacy 'chain B' gateway ingress "
            "(handlers/message_handler → TaskOrchestrator).  The canonical "
            "server ingress is websocket_handler → DeviceRouter (chain A).  "
            "PR-S6 adds a deprecation docstring, a LEGACY PATH GUARDRAIL in "
            "__init__, and a LEGACY_PATH_REGISTRY entry.  MessageHandler is "
            "retained so existing chain-B integrations do not immediately break; "
            "new routing must use websocket_handler (chain A) only."
        ),
        canonical_replacement=(
            "galaxy_gateway/websocket_handler.py  (chain A: websocket_handler → DeviceRouter)"
        ),
    ),

    # ── PR-S7: Final compatibility demotion — last remaining legacy control surfaces

    PurgeDecision(
        asset_path="galaxy_gateway/task_decomposer.py::TaskDecomposer",
        status=PurgeStatus.WRAPPER_HARDENED,
        pr="PR-S7",
        rationale=(
            "TaskDecomposer is a legacy rule-based task splitter that creates "
            "sub-tasks independently of the canonical TaskGraph "
            "(core.task_graph).  PR-S7 adds a deprecation docstring, a LEGACY "
            "PATH GUARDRAIL in __init__, and a LEGACY_PATH_REGISTRY entry.  "
            "The class is retained for backward compatibility; new task "
            "decomposition must use core.task_graph.TaskGraph directly."
        ),
        canonical_replacement="core/task_graph.py  (core.task_graph.TaskGraph)",
    ),
    PurgeDecision(
        asset_path="galaxy_gateway/task_decomposer.py::IntelligentTaskPlanner",
        status=PurgeStatus.WRAPPER_HARDENED,
        pr="PR-S7",
        rationale=(
            "IntelligentTaskPlanner is a legacy LLM-based task planner that "
            "generates sub-tasks independently of the canonical OpenClawd → "
            "CommandRouter → TaskGraph pipeline.  PR-S7 adds a deprecation "
            "docstring, a LEGACY PATH GUARDRAIL in __init__, and a "
            "LEGACY_PATH_REGISTRY entry.  Retained for backward compatibility; "
            "new planning must use core.e2e_orchestrator.process_user_input()."
        ),
        canonical_replacement=(
            "core/e2e_orchestrator.py  (core.e2e_orchestrator.process_user_input)"
        ),
    ),
    PurgeDecision(
        asset_path="galaxy_gateway/capability_registry.py::GatewayCapabilityRegistry",
        status=PurgeStatus.WRAPPER_HARDENED,
        pr="PR-S7",
        rationale=(
            "GatewayCapabilityRegistry is a legacy in-gateway per-device "
            "action-schema store introduced before core.capability_bus "
            "(CapabilityBus) existed.  PR-S7 adds a deprecation docstring, a "
            "LEGACY PATH GUARDRAIL in __init__, and a LEGACY_PATH_REGISTRY "
            "entry.  Retained so existing DeviceRouter capability-report "
            "pathways do not immediately break; new capability registration "
            "must use core.capability_bus.CapabilityBus."
        ),
        canonical_replacement=(
            "core/capability_bus.py  (core.capability_bus.get_capability_bus)"
        ),
    ),
    PurgeDecision(
        asset_path="galaxy_gateway/aip_protocol_v2.py",
        status=PurgeStatus.HARD_DISABLED,
        pr="PR-S7",
        rationale=(
            "galaxy_gateway.aip_protocol_v2 is the legacy AIP v2.0 protocol "
            "module, superseded by galaxy_gateway.protocol.aip_v3 (v3 single "
            "source of truth).  The module already raises ImportError on import "
            "to prevent accidental use.  PR-S7 formalises this as a "
            "HARD_DISABLED PURGE_REGISTRY entry so the purge audit log is "
            "complete and tooling can verify the hard-disable is still in effect."
        ),
        canonical_replacement=(
            "galaxy_gateway/protocol/aip_v3.py  "
            "and  galaxy_gateway/protocol/compat.py::parse_message_compat"
        ),
    ),

    # ── Phase-A consolidation: capability naming ambiguity removed ────────

    PurgeDecision(
        asset_path="core/hybrid_executor.py::CapabilityRegistry",
        status=PurgeStatus.DEAD_REFERENCE_REMOVED,
        pr="PR-consolidation-A",
        rationale=(
            "The class ``CapabilityRegistry`` in core/hybrid_executor.py was "
            "ambiguously named — it appeared to be a capability registry but was "
            "only a local per-app execution-level preference store "
            "(A2A/GUI/VLM priority order per app_id), completely unrelated to the "
            "system-wide capability bus.  Phase-A renames it to "
            "``AppExecutionCapabilityRegistry`` to eliminate the naming "
            "conflict and adds the ``APP_EXECUTION_CAPABILITY_REGISTRY_RENAMED`` "
            "sentinel."
        ),
        canonical_replacement=(
            "core/hybrid_executor.py::AppExecutionCapabilityRegistry  "
            "(local app execution preferences)  "
            "and  core/agent/capability_registry.py::CapabilityRegistry  "
            "(system-wide canonical capability truth source)"
        ),
    ),

    # ── Phase-A consolidation: scheduler legacy tool naming demoted ───────

    PurgeDecision(
        asset_path="core/scheduler.py::inject_mcp_tools (mcp_ prefix)",
        status=PurgeStatus.WRAPPER_HARDENED,
        pr="PR-consolidation-A",
        rationale=(
            "Scheduler.inject_mcp_tools() previously emitted tools under the "
            "legacy single-underscore prefix ``mcp_<server_id>_<tool_name>``.  "
            "Phase-A changes it to emit the canonical double-underscore form "
            "``mcp__<server_id>__<tool_name>`` as the primary exposed name.  "
            "The dispatch path (_exec_mcp_tool / _execute_tool) retains a "
            "compatibility branch for the legacy ``mcp_`` prefix so existing "
            "integrations are not broken, but new tools MUST use the canonical form."
        ),
        canonical_replacement=(
            "core/scheduler.py::inject_mcp_tools — now emits mcp__<server>__<tool>"
        ),
    ),
    PurgeDecision(
        asset_path="core/scheduler.py::inject_skill_tools (skill_ prefix)",
        status=PurgeStatus.WRAPPER_HARDENED,
        pr="PR-consolidation-A",
        rationale=(
            "Scheduler.inject_skill_tools() previously emitted tools under the "
            "legacy single-underscore prefix ``skill_<name>``.  Phase-A changes "
            "it to emit the canonical double-underscore form ``skill__<skill_id>`` "
            "as the primary exposed name.  The dispatch path retains a compat "
            "branch for ``skill_`` so existing callers are not immediately broken."
        ),
        canonical_replacement=(
            "core/scheduler.py::inject_skill_tools — now emits skill__<id>"
        ),
    ),
    PurgeDecision(
        asset_path="core/scheduler.py::_dispatch_tool_call (call_ prefix)",
        status=PurgeStatus.WRAPPER_HARDENED,
        pr="PR-consolidation-A",
        rationale=(
            "The legacy ``call_Node_*`` (and generic ``call_``) tool naming used "
            "in scheduler dispatch predates the canonical ``node__<id>__<action>`` "
            "scheme.  Phase-A demotes these to explicit compat aliases in "
            "_execute_tool() with a logger.debug warning so callers are "
            "informed to migrate.  The canonical ``node__`` path is now checked "
            "first."
        ),
        canonical_replacement=(
            "node__<node_id>__<action>  (canonical node tool naming)"
        ),
    ),

    # ── Phase-B consolidation: callable-node baseline startup integration ──

    PurgeDecision(
        asset_path="launcher/node_startup.py::no callable-node classification",
        status=PurgeStatus.WRAPPER_HARDENED,
        pr="PR-consolidation-B",
        rationale=(
            "NodeSystemLauncher previously only distinguished startup-ready "
            "nodes (via get_active_nodes / get_tier_nodes / get_readiness_baseline) "
            "but provided no runtime view of which started nodes are callable "
            "by OpenClawd.  PR-529 Phase-B adds "
            "get_callable_node_classification(), which queries "
            "NodeFabricRegistry and applies is_callable_by_openclawd() to "
            "separate: callable_nodes (CAPABILITY_NODE), service_nodes, "
            "legacy_nodes (LEGACY_ORCHESTRATOR_NODE), non_callable_nodes "
            "(EXPERIMENTAL/ARCHIVED), and unregistered_startup_nodes."
        ),
        canonical_replacement=(
            "launcher/node_startup.py::"
            "NodeSystemLauncher.get_callable_node_classification()"
        ),
    ),
    PurgeDecision(
        asset_path="scripts/validate_runtime.py::no callable-startup check",
        status=PurgeStatus.WRAPPER_HARDENED,
        pr="PR-consolidation-B",
        rationale=(
            "validate_runtime.py previously had no check confirming the "
            "callable-node baseline was wired into the startup layer. "
            "PR-529 Phase-B adds check_callable_startup_integration() which "
            "verifies the CALLABLE_BASELINE_STARTUP_INTEGRATION sentinel and "
            "the presence of NodeSystemLauncher.get_callable_node_classification."
        ),
        canonical_replacement=(
            "scripts/validate_runtime.py::check_callable_startup_integration()"
        ),
    ),

    # ── PR-M: Legacy path retirement and canonical-only enforcement pass ──

    PurgeDecision(
        asset_path="galaxy_gateway/smart_transport_router.py::SmartTransportRouter",
        status=PurgeStatus.WRAPPER_HARDENED,
        pr="PR-M",
        rationale=(
            "SmartTransportRouter is a legacy transport-selection helper that "
            "chooses between WebRTC, Scrcpy, ADB, and HTTP outside the canonical "
            "DeviceRouter → galaxy_gateway.routing.dispatch pipeline.  "
            "PR-M adds a deprecation docstring, a LEGACY PATH GUARDRAIL in "
            "__init__, and a LEGACY_PATH_REGISTRY entry.  The class is retained "
            "for backward compatibility; new transport dispatch must use "
            "DeviceRouter.route_task() → galaxy_gateway.routing.dispatch."
        ),
        canonical_replacement=(
            "galaxy_gateway/device_router.py  (DeviceRouter.route_task)  "
            "→  galaxy_gateway/routing/dispatch.py  (dispatch_to_websocket)"
        ),
    ),
    PurgeDecision(
        asset_path="galaxy_gateway/enhanced_nlu_v2.py::EnhancedNLUEngineV2",
        status=PurgeStatus.WRAPPER_HARDENED,
        pr="PR-M",
        rationale=(
            "EnhancedNLUEngineV2 is a legacy LLM+rule hybrid NLU engine that "
            "resolves device intent outside the canonical OpenClawd → "
            "CommandRouter → TaskEnvelope pipeline, maintaining its own device "
            "registry and LLM client as parallel authorities.  "
            "PR-M adds a deprecation docstring, a LEGACY PATH GUARDRAIL in "
            "__init__, and a LEGACY_PATH_REGISTRY entry.  The class is retained "
            "for backward compatibility; new intent processing must use "
            "core.e2e_orchestrator.process_user_input()."
        ),
        canonical_replacement=(
            "core/e2e_orchestrator.py  (core.e2e_orchestrator.process_user_input)"
        ),
    ),
    PurgeDecision(
        asset_path="galaxy_gateway/session_roaming.py::SessionRoamingManager",
        status=PurgeStatus.WRAPPER_HARDENED,
        pr="PR-M",
        rationale=(
            "SessionRoamingManager is a legacy session migration manager that "
            "directly uses CrossDeviceCoordinator (a legacy fallback coordinator) "
            "and core.device_communication.send_command, bypassing the canonical "
            "CanonicalTask → TaskEnvelope → CommandRouter.route_envelope() spine.  "
            "PR-M adds a deprecation docstring, a LEGACY PATH GUARDRAIL in "
            "__init__, and a LEGACY_PATH_REGISTRY entry.  The class is retained "
            "for backward compatibility; new session continuity and cross-device "
            "handoff must use the canonical session axis and attached-runtime "
            "session layer."
        ),
        canonical_replacement=(
            "core/canonical_session_axis.py  +  core/attached_runtime_session.py"
        ),
    ),
)

# ── PR-convergence: Enforce single authoritative path and default-off legacy ──

PURGE_REGISTRY = PURGE_REGISTRY + (
    PurgeDecision(
        asset_path=(
            "core/canonical_authoritative_path_convergence.py"
            "::CANONICAL_PATH_INVENTORY"
        ),
        status=PurgeStatus.WRAPPER_HARDENED,
        pr="PR-convergence",
        rationale=(
            "PR-convergence establishes CANONICAL_PATH_INVENTORY as the single "
            "machine-readable surface classifying every runtime path by its "
            "authoritative role (canonical / compat_allowed / observation_only / "
            "deprecated_live / fully_blocked).  "
            "Prior PRs (PR-8 through PR-M) defined blocking machinery and legacy "
            "registries but had no single module that proved the canonical path was "
            "actually the default and that legacy paths were default-off.  "
            "This entry records that the convergence inventory is now hardened and "
            "verifiable by tests and operator tooling."
        ),
        canonical_replacement=(
            "core/canonical_authoritative_path_convergence.py"
            "  (CANONICAL_PATH_INVENTORY + enforce_canonical_selection)"
        ),
    ),
    PurgeDecision(
        asset_path=(
            "core/canonical_authoritative_path_convergence.py"
            "::DEFAULT_OFF_LEGACY_BEHAVIOR_POLICY"
        ),
        status=PurgeStatus.WRAPPER_HARDENED,
        pr="PR-convergence",
        rationale=(
            "PR-convergence introduces DEFAULT_OFF_LEGACY_BEHAVIOR_POLICY and "
            "is_legacy_default_off() as the formal machine-checkable gate for "
            "default-off legacy behavior.  "
            "Legacy paths classified as deprecated_live or fully_blocked in "
            "CANONICAL_PATH_INVENTORY return True from is_legacy_default_off(), "
            "proving they are not the default runtime choice."
        ),
        canonical_replacement=(
            "core/canonical_authoritative_path_convergence.py::is_legacy_default_off()"
        ),
    ),
    PurgeDecision(
        asset_path=(
            "core/canonical_authoritative_path_convergence.py"
            "::ANDROID_COMPAT_INFLUENCE_MUST_PASS_INGRESS_GATE_POLICY"
        ),
        status=PurgeStatus.WRAPPER_HARDENED,
        pr="PR-convergence",
        rationale=(
            "PR-convergence formally documents and enforces the Android compat "
            "influence boundary: all Android-originated compat/legacy participant "
            "signals MUST pass through "
            "core.android_participant_truth_ingress.ingest_android_participant_truth_message "
            "before reaching V2 canonical state.  Direct writes from Android compat "
            "signals bypassing this gate are blocked.  "
            "This policy was implicit before PR-convergence; it is now machine-readable "
            "and verifiable in tests."
        ),
        canonical_replacement=(
            "core/android_participant_truth_ingress.py"
            "::ingest_android_participant_truth_message()"
        ),
    ),
    PurgeDecision(
        asset_path=(
            "core/orchestration_authority/legacy_paths.py"
            "::PR-convergence entries"
        ),
        status=PurgeStatus.WRAPPER_HARDENED,
        pr="PR-convergence",
        rationale=(
            "PR-convergence adds formal LEGACY_PATH_REGISTRY entries for: "
            "(1) Android participant truth ingress canonical gate, "
            "(2) Android delegated signal ingress canonical gate, "
            "(3) compat_extract_signal_kind compat-allowed boundary, "
            "(4) DelegatedFlowAcceptanceGate and DelegatedFlowReadinessGate canonical surfaces, "
            "(5) observation-only audit surfaces (AndroidDelegatedRuntimeAuditRecord, "
            "ReplayFoundation, OperatorSurface).  "
            "These entries complete the registry classification so every path "
            "that can reach a canonical surface has an explicit role record."
        ),
        canonical_replacement=None,
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
