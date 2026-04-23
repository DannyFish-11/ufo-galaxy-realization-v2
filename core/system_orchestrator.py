"""
core/system_orchestrator.py — Canonical staged bring-up contract
=================================================================

**PR-2: Canonical System Orchestrator**

This module defines the authoritative staged startup contract for Galaxy-Nexus.
``main.py`` is the canonical process entrypoint that drives this orchestrator.

``unified_launcher.py`` is a **subordinate** launcher component invoked during
Phase 4–6 of the bring-up sequence.  It is NOT a competing top-level startup
authority.

Staged bring-up phases
----------------------
.. code-block:: text

    Phase 1 — LOAD_CONFIG           Load unified configuration baseline
    Phase 2 — RESOLVE_MODE          Resolve current system mode
    Phase 3 — ENV_CHECKS            Environment / bootstrap checks
    Phase 4 — BACKGROUND_SUBSYSTEMS Background subsystem bring-up hooks
    Phase 5 — RUNTIME_SUBJECT       Runtime subject bring-up hooks
    Phase 6 — DESKTOP_SURFACE       Desktop surface bring-up hooks
    Phase 7 — READINESS_SUMMARY     Final readiness summary / status report

Later PRs may extend individual phases with:
- Mode-aware NATS semantics (Phase 4)
- Full FabricSubsystem lifecycle (Phase 4)
- Stronger desktop readiness handling (Phase 6)

Authority sentinel
------------------
``SYSTEM_ORCHESTRATOR_AUTHORITY`` is the unique string token that identifies
``main.py`` as the canonical system orchestrator entrypoint.  CI and
validation tooling may verify this sentinel's presence to confirm orchestrator
governance.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("Galaxy.Orchestrator")

# ---------------------------------------------------------------------------
# Authority sentinel — used by validate_runtime.py and CI guardrails
# ---------------------------------------------------------------------------

SYSTEM_ORCHESTRATOR_AUTHORITY: str = (
    "main.py:SYSTEM_ORCHESTRATOR — canonical staged bring-up contract (PR-2)"
)


# ---------------------------------------------------------------------------
# Startup phase contract
# ---------------------------------------------------------------------------

class StartupPhase(Enum):
    """Ordered startup phases for the canonical bring-up sequence."""

    LOAD_CONFIG = 1          # Phase 1 — Load unified configuration baseline
    RESOLVE_MODE = 2         # Phase 2 — Resolve current system mode
    ENV_CHECKS = 3           # Phase 3 — Environment / bootstrap checks
    BACKGROUND_SUBSYSTEMS = 4  # Phase 4 — Background subsystem bring-up hooks
    RUNTIME_SUBJECT = 5      # Phase 5 — Runtime subject bring-up hooks
    DESKTOP_SURFACE = 6      # Phase 6 — Desktop surface bring-up hooks
    READINESS_SUMMARY = 7    # Phase 7 — Final readiness summary


class PhaseStatus(Enum):
    """Result status for a single startup phase."""

    PENDING = auto()
    RUNNING = auto()
    OK = auto()
    DEGRADED = auto()
    SKIPPED = auto()
    FAILED = auto()


# ---------------------------------------------------------------------------
# Phase result — typed, inspectable, extensible
# ---------------------------------------------------------------------------

@dataclass
class PhaseResult:
    """Outcome of a single startup phase."""

    phase: StartupPhase
    status: PhaseStatus
    detail: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True when phase completed without hard failure."""
        return self.status in (PhaseStatus.OK, PhaseStatus.DEGRADED, PhaseStatus.SKIPPED)

    def __str__(self) -> str:
        return f"[{self.phase.name}] {self.status.name}" + (
            f" — {self.detail}" if self.detail else ""
        )


# ---------------------------------------------------------------------------
# Readiness summary
# ---------------------------------------------------------------------------

class OrchestratorReadiness(Enum):
    """Overall readiness state after all phases have run."""

    READY = "READY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


@dataclass
class StartupSummary:
    """Aggregated result from a complete bring-up sequence."""

    phase_results: List[PhaseResult] = field(default_factory=list)
    readiness: OrchestratorReadiness = OrchestratorReadiness.READY
    system_mode: str = "desktop-local"
    notes: List[str] = field(default_factory=list)

    def add_result(self, result: PhaseResult) -> None:
        self.phase_results.append(result)
        if result.status == PhaseStatus.FAILED:
            self.readiness = OrchestratorReadiness.FAILED
        elif result.status == PhaseStatus.DEGRADED and self.readiness == OrchestratorReadiness.READY:
            self.readiness = OrchestratorReadiness.DEGRADED

    def is_ready(self) -> bool:
        return self.readiness != OrchestratorReadiness.FAILED

    def __str__(self) -> str:
        lines = [f"Startup readiness: {self.readiness.value}"]
        lines.append(f"System mode: {self.system_mode}")
        for r in self.phase_results:
            lines.append(f"  {r}")
        if self.notes:
            lines.extend(self.notes)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Phase hook type alias — simple callable returning PhaseResult
# ---------------------------------------------------------------------------

PhaseHook = Callable[[], PhaseResult]


# ---------------------------------------------------------------------------
# SystemOrchestrator — the staged bring-up engine
# ---------------------------------------------------------------------------

class SystemOrchestrator:
    """
    Staged bring-up engine for Galaxy-Nexus.

    ``main.py`` instantiates this class and calls :meth:`run_startup_sequence`
    to execute all phases in order.  Each phase may be extended by later PRs
    by supplying ``extra_hooks`` for any given :class:`StartupPhase`.

    Design notes
    ~~~~~~~~~~~~
    - Phases run sequentially so that earlier phases can gate later ones.
    - A ``FAILED`` phase causes later phases to be skipped unless
      ``continue_on_failure=True``.
    - All exceptions inside phase hooks are caught and surfaced as
      ``PhaseStatus.DEGRADED`` (non-fatal) unless the hook explicitly raises
      after setting ``PhaseStatus.FAILED``.
    """

    def __init__(
        self,
        continue_on_failure: bool = False,
    ) -> None:
        self.continue_on_failure = continue_on_failure
        self._extra_hooks: Dict[StartupPhase, List[PhaseHook]] = {}

    # ------------------------------------------------------------------
    # Hook registration — extension point for later PRs
    # ------------------------------------------------------------------

    def register_hook(self, phase: StartupPhase, hook: PhaseHook) -> None:
        """Register an additional hook to run during *phase*."""
        self._extra_hooks.setdefault(phase, []).append(hook)

    # ------------------------------------------------------------------
    # Internal phase runners — each returns a PhaseResult
    # ------------------------------------------------------------------

    def _run_phase_1_load_config(self) -> PhaseResult:
        """Phase 1 — Load unified configuration baseline."""
        logger.info("[Phase 1] Loading unified configuration …")
        try:
            from core.unified_config import get_config
            cfg = get_config()
            detail = "unified config loaded"
            if hasattr(cfg, "get_status_dict"):
                status_d = cfg.get_status_dict()
                llm_count = sum(1 for v in status_d.get("llm_apis", {}).values() if v)
                detail = f"unified config loaded — {llm_count} LLM API(s) configured"
            return PhaseResult(
                phase=StartupPhase.LOAD_CONFIG,
                status=PhaseStatus.OK,
                detail=detail,
                data={"config_loaded": True},
            )
        except Exception as exc:
            logger.warning("[Phase 1] Config load degraded: %s", exc)
            return PhaseResult(
                phase=StartupPhase.LOAD_CONFIG,
                status=PhaseStatus.DEGRADED,
                detail=f"config load degraded — {exc}",
            )

    def _run_phase_2_resolve_mode(self) -> PhaseResult:
        """Phase 2 — Resolve current system mode."""
        import os
        logger.info("[Phase 2] Resolving system mode …")
        mode = os.environ.get("GALAXY_SYSTEM_MODE", "desktop-local").strip() or "desktop-local"
        nats_enabled = os.environ.get("GALAXY_NATS_ENABLED", "").lower() in ("true", "1")
        cross_device = os.environ.get("GALAXY_CROSS_DEVICE_ENABLED", "").lower() in ("true", "1")
        # Cross-device inference: an explicitly set GALAXY_NATS_URL is treated as
        # a signal that cross-device mode is intended, even if
        # GALAXY_CROSS_DEVICE_ENABLED is not explicitly set.  NATS is the
        # control-plane transport for multi-device operation; if the operator
        # has pointed the system at a remote NATS server, cross-device mode is
        # the expected operating context.
        if not cross_device and os.environ.get("GALAXY_NATS_URL", "").strip():
            cross_device = True
        if cross_device:
            mode = "desktop-cross-device"
        detail = f"mode={mode}, nats_enabled={nats_enabled}, cross_device={cross_device}"
        logger.info("[Phase 2] %s", detail)
        return PhaseResult(
            phase=StartupPhase.RESOLVE_MODE,
            status=PhaseStatus.OK,
            detail=detail,
            data={"system_mode": mode, "nats_enabled": nats_enabled, "cross_device": cross_device},
        )

    def _run_phase_3_env_checks(self) -> PhaseResult:
        """Phase 3 — Environment / bootstrap checks."""
        logger.info("[Phase 3] Running environment / bootstrap checks …")
        issues: List[str] = []
        try:
            from core.config_preflight import run_preflight
            run_preflight()
        except ImportError:
            pass  # preflight module optional at this phase
        except Exception as exc:
            issues.append(f"preflight: {exc}")

        if issues:
            return PhaseResult(
                phase=StartupPhase.ENV_CHECKS,
                status=PhaseStatus.DEGRADED,
                detail="; ".join(issues),
            )
        return PhaseResult(
            phase=StartupPhase.ENV_CHECKS,
            status=PhaseStatus.OK,
            detail="environment checks passed",
        )

    def _run_phase_4_background_subsystems(self) -> PhaseResult:
        """Phase 4 — Background subsystem readiness checks (verifiable).

        This phase keeps orchestration ownership in ``main.py`` while performing
        low-cost, externally explainable checks that verify the runtime can route
        and execute through canonical surfaces.
        """
        logger.info("[Phase 4] Verifying background subsystem readiness …")
        diagnostics: Dict[str, Any] = {
            "delegate": "unified_launcher.GalaxyUnified",
            "checks": {},
            "readiness_notes": [],
        }
        issues: List[str] = []

        try:
            from core.command_router import get_command_router

            router = get_command_router()
            diagnostics["checks"]["command_router_available"] = router is not None
            if router is None:
                issues.append("command_router_unavailable")
        except Exception as exc:
            diagnostics["checks"]["command_router_available"] = False
            issues.append(f"command_router_error:{exc}")

        try:
            from core.runtime.source_dispatch_orchestrator import build_source_dispatch_plan

            plan = build_source_dispatch_plan()
            plan_ready = bool(getattr(plan, "ready", False))
            readiness_notes = list(getattr(plan, "readiness_notes", []) or [])
            diagnostics["checks"]["dispatch_plan_ready"] = plan_ready
            diagnostics["readiness_notes"] = readiness_notes
            if not plan_ready:
                issues.append("dispatch_plan_not_ready")
                issues.extend(readiness_notes)
        except Exception as exc:
            diagnostics["checks"]["dispatch_plan_ready"] = False
            issues.append(f"dispatch_plan_error:{exc}")

        # PR-A: Trigger mesh session recovery so that any non-terminal sessions
        # persisted from a previous run are surfaced before normal operation
        # resumes.  This is the real startup/bootstrap callsite for recover_sessions().
        try:
            from core.multi_device_runtime_harness import get_multi_device_runtime_harness

            _harness = get_multi_device_runtime_harness()
            _recovered = _harness.recover_sessions()
            diagnostics["checks"]["mesh_sessions_recovered"] = len(_recovered)
            logger.info(
                "[Phase 4] Multi-device session recovery: %d recoverable session(s) found.",
                len(_recovered),
            )
        except Exception as exc:
            diagnostics["checks"]["mesh_sessions_recovered"] = 0
            logger.debug("[Phase 4] Multi-device session recovery skipped — %s", exc)

        # PR-RECOVERY: Run the canonical full startup recovery coordinator.
        # This wires RuntimeRestartRecoveryCoordinator into the production
        # startup path, ensuring that all durable lifecycle state
        # (BodyMeshRegistry, WebRTC binding reset, hybrid orchestration
        # continuity, and in-flight task lifecycle records) is recovered
        # before the runtime begins processing new work.
        try:
            from core.runtime_restart_recovery import run_startup_recovery

            _recovery_report = run_startup_recovery()
            diagnostics["checks"]["startup_recovery_completed"] = True
            diagnostics["startup_recovery"] = {
                "recovery_id": _recovery_report.recovery_id,
                "mesh_sessions_recovered": _recovery_report.mesh_sessions_recovered,
                "body_mesh_entries_restored": _recovery_report.body_mesh_entries_restored,
                "hybrid_executions_interrupted": _recovery_report.hybrid_executions_interrupted,
                "hybrid_executions_restored": _recovery_report.hybrid_executions_restored,
                "inflight_tasks_recovered": _recovery_report.inflight_tasks_recovered,
                "inflight_tasks_resumable": _recovery_report.inflight_tasks_resumable,
                "inflight_tasks_replay_only": _recovery_report.inflight_tasks_replay_only,
                "inflight_tasks_reissuable": _recovery_report.inflight_tasks_reissuable,
                "inflight_tasks_terminal": _recovery_report.inflight_tasks_terminal,
                "has_errors": _recovery_report.has_errors,
                "errors": list(_recovery_report.errors),
            }
            if _recovery_report.has_errors:
                logger.warning(
                    "[Phase 4] Startup recovery completed with errors: %s",
                    _recovery_report.errors,
                )
            else:
                logger.info(
                    "[Phase 4] Startup recovery completed: recovery_id=%s "
                    "mesh=%d body=%d hybrid_interrupted=%d hybrid_restored=%d "
                    "inflight=%d (resumable=%d replay=%d reissue=%d terminal=%d)",
                    _recovery_report.recovery_id,
                    _recovery_report.mesh_sessions_recovered,
                    _recovery_report.body_mesh_entries_restored,
                    _recovery_report.hybrid_executions_interrupted,
                    _recovery_report.hybrid_executions_restored,
                    _recovery_report.inflight_tasks_recovered,
                    _recovery_report.inflight_tasks_resumable,
                    _recovery_report.inflight_tasks_replay_only,
                    _recovery_report.inflight_tasks_reissuable,
                    _recovery_report.inflight_tasks_terminal,
                )
        except Exception as exc:
            diagnostics["checks"]["startup_recovery_completed"] = False
            diagnostics["startup_recovery"] = {"error": str(exc)}
            logger.warning("[Phase 4] Startup recovery skipped — %s", exc)

        # PR-RECOVERY: Restore the in-memory task lifecycle registry from the
        # durable snapshot so that previously in-flight task records are
        # re-populated before the runtime begins accepting new work.  Records
        # whose task_id is already pending are not overwritten.
        try:
            from core.task_envelope_lifecycle_registry import get_lifecycle_registry

            _registry = get_lifecycle_registry()
            _restored_count = _registry.restore_from_snapshot()
            diagnostics["checks"]["lifecycle_registry_restored"] = True
            diagnostics["lifecycle_registry_restored_count"] = _restored_count
            logger.info(
                "[Phase 4] Lifecycle registry restored %d record(s) from durable snapshot.",
                _restored_count,
            )
        except Exception as exc:
            diagnostics["checks"]["lifecycle_registry_restored"] = False
            diagnostics["lifecycle_registry_restored_count"] = 0
            logger.debug("[Phase 4] Lifecycle registry restore skipped — %s", exc)

        if issues:
            return PhaseResult(
                phase=StartupPhase.BACKGROUND_SUBSYSTEMS,
                status=PhaseStatus.DEGRADED,
                detail="background readiness degraded — " + "; ".join(issues),
                data=diagnostics,
            )

        return PhaseResult(
            phase=StartupPhase.BACKGROUND_SUBSYSTEMS,
            status=PhaseStatus.OK,
            detail="background readiness verified for canonical routing",
            data=diagnostics,
        )

    def _run_phase_5_runtime_subject(self) -> PhaseResult:
        """Phase 5 — Runtime subject bring-up hooks.

        Runtime subject: DesktopPresenceRuntime → OpenClawd.
        This phase confirms the subject authority chain is importable and
        will be activated during the async bring-up driven by Phase 4.
        """
        logger.info("[Phase 5] Beginning runtime subject bring-up hooks …")
        issues: List[str] = []
        for mod_name, cls_name in [
            ("core.desktop_presence_runtime", "DesktopPresenceRuntime"),
            ("core.openclawd", "OpenClawd"),
        ]:
            try:
                import importlib
                mod = importlib.import_module(mod_name)
                if not hasattr(mod, cls_name):
                    issues.append(f"{cls_name} missing from {mod_name}")
            except Exception as exc:
                issues.append(f"{mod_name}: {exc}")

        if issues:
            return PhaseResult(
                phase=StartupPhase.RUNTIME_SUBJECT,
                status=PhaseStatus.DEGRADED,
                detail="; ".join(issues),
            )
        return PhaseResult(
            phase=StartupPhase.RUNTIME_SUBJECT,
            status=PhaseStatus.OK,
            detail="runtime subject authority chain importable",
        )

    def _run_phase_6_desktop_surface(self) -> PhaseResult:
        """Phase 6 — Desktop surface bring-up hooks.

        Desktop surface: windows_client/status_board_v2 (active desktop status).
        This phase is a hook point for later PRs to add stronger desktop
        readiness semantics.
        """
        logger.info("[Phase 6] Beginning desktop surface bring-up hooks …")
        try:
            import importlib
            importlib.import_module("windows_client.status_board_v2")
            return PhaseResult(
                phase=StartupPhase.DESKTOP_SURFACE,
                status=PhaseStatus.OK,
                detail="desktop surface module importable",
            )
        except ImportError:
            return PhaseResult(
                phase=StartupPhase.DESKTOP_SURFACE,
                status=PhaseStatus.DEGRADED,
                detail="desktop surface module not importable (non-fatal)",
            )
        except Exception as exc:
            return PhaseResult(
                phase=StartupPhase.DESKTOP_SURFACE,
                status=PhaseStatus.DEGRADED,
                detail=f"desktop surface degraded: {exc}",
            )

    def _run_phase_7_readiness_summary(self, summary: StartupSummary) -> PhaseResult:
        """Phase 7 — Final readiness summary / status report."""
        logger.info("[Phase 7] Producing final readiness summary …")
        detail = (
            f"readiness={summary.readiness.value}, "
            f"phases_ok={sum(1 for r in summary.phase_results if r.ok)}/"
            f"{len(summary.phase_results)}"
        )
        logger.info("[Phase 7] %s", detail)
        return PhaseResult(
            phase=StartupPhase.READINESS_SUMMARY,
            status=PhaseStatus.OK,
            detail=detail,
            data={
                "readiness": summary.readiness.value,
                "system_mode": summary.system_mode,
            },
        )

    # ------------------------------------------------------------------
    # Main entry-point
    # ------------------------------------------------------------------

    def run_startup_sequence(self) -> StartupSummary:
        """Execute all startup phases in order and return a :class:`StartupSummary`.

        Phases run sequentially.  If a phase returns ``FAILED`` and
        ``continue_on_failure`` is ``False`` (the default), remaining phases
        are marked ``SKIPPED``.

        Extra hooks registered via :meth:`register_hook` run immediately after
        the built-in logic for each phase and can supplement or override the
        default result.
        """
        summary = StartupSummary()
        failed = False

        _phase_runners = [
            (StartupPhase.LOAD_CONFIG, self._run_phase_1_load_config),
            (StartupPhase.RESOLVE_MODE, self._run_phase_2_resolve_mode),
            (StartupPhase.ENV_CHECKS, self._run_phase_3_env_checks),
            (StartupPhase.BACKGROUND_SUBSYSTEMS, self._run_phase_4_background_subsystems),
            (StartupPhase.RUNTIME_SUBJECT, self._run_phase_5_runtime_subject),
            (StartupPhase.DESKTOP_SURFACE, self._run_phase_6_desktop_surface),
        ]

        for phase, runner in _phase_runners:
            if failed and not self.continue_on_failure:
                result = PhaseResult(
                    phase=phase,
                    status=PhaseStatus.SKIPPED,
                    detail="skipped due to earlier failure",
                )
            else:
                result = runner()
                # Run any extra hooks for this phase
                for hook in self._extra_hooks.get(phase, []):
                    try:
                        hook_result = hook()
                        if hook_result.status == PhaseStatus.FAILED:
                            result = hook_result
                        elif hook_result.status == PhaseStatus.DEGRADED and result.ok:
                            result = hook_result
                    except Exception as exc:
                        logger.warning("Extra hook for %s raised: %s", phase.name, exc)

            summary.add_result(result)
            logger.info("  %s", result)

            if result.status == PhaseStatus.FAILED:
                failed = True

        # Extract system_mode from Phase 2 result
        for r in summary.phase_results:
            if r.phase == StartupPhase.RESOLVE_MODE and r.data.get("system_mode"):
                summary.system_mode = r.data["system_mode"]
                break

        # Phase 7 — readiness summary (always runs)
        summary_result = self._run_phase_7_readiness_summary(summary)
        summary.add_result(summary_result)

        return summary
