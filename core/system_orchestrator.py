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
import os
import subprocess
import sys
import threading
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
# Strict-preflight sentinel — used by CI and validate_runtime.py
# ---------------------------------------------------------------------------

STRICT_PREFLIGHT_ENV_VAR: str = "GALAXY_STRICT_PREFLIGHT"
"""Environment variable that enables the strict preflight failure mode.

When set to ``1`` / ``true`` / ``yes``, CRITICAL preflight failures and
unhandled Phase-3 exceptions abort startup rather than degrading silently.
This sentinel allows CI tooling to confirm the strict-mode guard is present.
"""

STRICT_AUTHORITY_CHECK_ENV_VAR: str = "GALAXY_STRICT_AUTHORITY_CHECK"
"""Environment variable that enables the strict authority boundary failure mode.

When set to ``1`` / ``true`` / ``yes``, Phase-7 center authority boundary
degradation causes startup to FAIL rather than continue in DEGRADED mode.
This sentinel allows CI tooling to confirm authority boundary enforcement is
present in the startup sequence.
"""


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
        strict_preflight: Optional[bool] = None,
    ) -> None:
        self.continue_on_failure = continue_on_failure
        # Resolve strict mode: explicit argument takes precedence over env var.
        if strict_preflight is None:
            strict_preflight = os.environ.get(STRICT_PREFLIGHT_ENV_VAR, "").lower() in (
                "1", "true", "yes"
            )
        self.strict_preflight: bool = strict_preflight
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
        """Phase 3 — Environment / bootstrap checks.

        In strict mode (``strict_preflight=True`` or
        ``GALAXY_STRICT_PREFLIGHT=1``), a CRITICAL preflight finding causes
        this phase to return ``PhaseStatus.FAILED`` rather than ``DEGRADED``,
        which will abort the startup sequence when ``continue_on_failure`` is
        ``False`` (the default).
        """
        logger.info("[Phase 3] Running environment / bootstrap checks …")
        issues: List[str] = []
        has_critical_failure = False
        try:
            from core.config_preflight import run_preflight, ConfigPreflightError
            report = run_preflight(dry_run=True)  # collect findings without raising
            if not report.ok:
                issues.append(
                    f"preflight: {len(report.critical_findings)} CRITICAL finding(s)"
                )
                if self.strict_preflight:
                    has_critical_failure = True
                    logger.error(
                        "[Phase 3] STRICT preflight: %d CRITICAL finding(s) — "
                        "aborting startup (GALAXY_STRICT_PREFLIGHT=1)",
                        len(report.critical_findings),
                    )
        except ImportError:
            pass  # preflight module optional at this phase
        except Exception as exc:
            issues.append(f"preflight: {exc}")
            if self.strict_preflight:
                has_critical_failure = True

        if has_critical_failure:
            return PhaseResult(
                phase=StartupPhase.ENV_CHECKS,
                status=PhaseStatus.FAILED,
                detail="; ".join(issues),
            )
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
        hard_failures: List[str] = []

        try:
            from core.command_router import get_command_router

            router = get_command_router()
            diagnostics["checks"]["command_router_available"] = router is not None
            if router is None:
                issues.append("command_router_unavailable")
        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
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
            logger.debug("Fallback triggered: %s", exc)
            diagnostics["checks"]["dispatch_plan_ready"] = False
            issues.append(f"dispatch_plan_error:{exc}")

        try:
            from core.nats_posture import evaluate_nats_posture

            nats_posture = evaluate_nats_posture()
            diagnostics["checks"]["nats_posture_assertion_ok"] = bool(
                nats_posture.get("assertion_ok", True)
            )
            diagnostics["nats_posture"] = nats_posture
            if not nats_posture.get("assertion_ok", True):
                reason = (
                    nats_posture.get("violation_reason")
                    or "nats_posture_violation_unknown_reason"
                )
                hard_failures.append(str(reason))
        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            diagnostics["checks"]["nats_posture_assertion_ok"] = False
            diagnostics["nats_posture"] = {"error": str(exc)}
            hard_failures.append(f"nats_posture_error:{exc}")

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
            logger.debug("Fallback triggered: %s", exc)
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
            logger.debug("Fallback triggered: %s", exc)
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
            logger.debug("Fallback triggered: %s", exc)
            diagnostics["checks"]["lifecycle_registry_restored"] = False
            diagnostics["lifecycle_registry_restored_count"] = 0
            logger.debug("[Phase 4] Lifecycle registry restore skipped — %s", exc)

        if hard_failures:
            parts: List[str] = []
            parts.append("hard_failures=" + ",".join(hard_failures))
            if issues:
                parts.append("degraded_issues=" + ",".join(issues))
            return PhaseResult(
                phase=StartupPhase.BACKGROUND_SUBSYSTEMS,
                status=PhaseStatus.FAILED,
                detail="background readiness failed — " + "; ".join(parts),
                data=diagnostics,
            )

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
        """Phase 6 -- Desktop surface bring-up.

        Launches the Electron three-state GUI as a detached subprocess.
        The three-state GUI (silent / liminal / manifest) is the primary
        desktop presence surface.  It is started via ``npm start`` in the
        ``electron/`` directory.

        If Electron is not available (npm/node missing or electron dir absent)
        the phase returns DEGRADED and the system continues without the GUI.
        """
        logger.info("[Phase 6] Desktop surface bring-up (Electron three-state GUI) ...")

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        electron_dir = os.path.join(project_root, "electron")

        # Check prerequisites
        if not os.path.isdir(electron_dir):
            return PhaseResult(
                phase=StartupPhase.DESKTOP_SURFACE,
                status=PhaseStatus.DEGRADED,
                detail="electron/ directory not found -- GUI not available",
            )

        # 预检 Node.js / npm 可用性（在调用 npm install 前主动探测，
        # 避免 FileNotFoundError 导致误导性错误信息 "Node.js not installed"）
        import shutil

        node_path = shutil.which("node")
        npm_path = shutil.which("npm")
        logger.debug("[Phase 6] Node.js detection — node=%s, npm=%s", node_path, npm_path)

        if not node_path:
            return PhaseResult(
                phase=StartupPhase.DESKTOP_SURFACE,
                status=PhaseStatus.DEGRADED,
                detail="Electron GUI skipped (Node.js not installed or not in PATH)",
            )

        # Check if node_modules exists (npm install has been run)
        node_modules = os.path.join(electron_dir, "node_modules")
        if not os.path.isdir(node_modules):
            if not npm_path:
                return PhaseResult(
                    phase=StartupPhase.DESKTOP_SURFACE,
                    status=PhaseStatus.DEGRADED,
                    detail="Electron GUI skipped (npm not in PATH — Node.js installed but npm missing)",
                )
            logger.warning("[Phase 6] electron/node_modules not found -- running npm install ...")
            try:
                npm_result = subprocess.run(
                    [npm_path, "install"],
                    cwd=electron_dir,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if npm_result.returncode != 0:
                    return PhaseResult(
                        phase=StartupPhase.DESKTOP_SURFACE,
                        status=PhaseStatus.DEGRADED,
                        detail=f"npm install failed: {npm_result.stderr[:200]}",
                    )
            except subprocess.TimeoutExpired:
                return PhaseResult(
                    phase=StartupPhase.DESKTOP_SURFACE,
                    status=PhaseStatus.DEGRADED,
                    detail="npm install timed out after 120s",
                )

        # Launch Electron as detached subprocess
        try:
            env = os.environ.copy()
            env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")

            # Use shell=False for security; npm start will run electron .
            process = subprocess.Popen(
                ["npm", "start"],
                cwd=electron_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                # Detached so Electron survives if Python parent exits
                start_new_task=True if sys.platform != "win32" else False,
            )

            # Start a background thread to drain stdout (prevents pipe buffer fill)
            threading.Thread(
                target=self._drain_electron_output,
                args=(process,),
                daemon=True,
                name="ElectronOutputDrainer",
            ).start()

            logger.info("[Phase 6] Electron GUI launched (pid=%d)", process.pid)
            return PhaseResult(
                phase=StartupPhase.DESKTOP_SURFACE,
                status=PhaseStatus.OK,
                detail=f"Electron GUI launched (pid={process.pid})",
                data={"electron_pid": process.pid},
            )

        except FileNotFoundError:
            return PhaseResult(
                phase=StartupPhase.DESKTOP_SURFACE,
                status=PhaseStatus.DEGRADED,
                detail="npm not found -- install Node.js to enable GUI",
            )
        except Exception as exc:
            return PhaseResult(
                phase=StartupPhase.DESKTOP_SURFACE,
                status=PhaseStatus.DEGRADED,
                detail=f"Electron launch failed: {exc}",
            )

    def _drain_electron_output(self, process: subprocess.Popen) -> None:
        """Drain Electron subprocess stdout to prevent pipe buffer deadlock."""
        if process.stdout is None:
            return
        try:
            for line in process.stdout:
                line = line.strip()
                if line:
                    # Log at DEBUG to avoid spamming INFO
                    logger.debug("[Electron] %s", line)
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

    def _run_phase_7_readiness_summary(self, summary: StartupSummary) -> PhaseResult:
        """Phase 7 — Final readiness summary / status report.

        This phase also runs the V6 center authority boundary integrity check
        (:func:`core.center_authority_boundary.assert_center_authority_intact`).
        A degraded or broken boundary is surfaced as ``DEGRADED`` in the phase
        result so that startup logs reflect the structural state without
        blocking the process from continuing (boundary failures are
        non-fatal to allow degraded-mode operation while the issue is
        investigated).

        Note: V6 is intentionally placed here — at the **boundary / startup /
        readiness layer** — and is **not** wired into per-request hot paths
        such as ``OpenClawd.process()`` or ``CommandRouter.route_envelope()``.
        """
        logger.info("[Phase 7] Producing final readiness summary …")
        detail = (
            f"readiness={summary.readiness.value}, "
            f"phases_ok={sum(1 for r in summary.phase_results if r.ok)}/"
            f"{len(summary.phase_results)}"
        )
        logger.info("[Phase 7] %s", detail)

        # V6 center authority boundary integrity check — boundary / startup layer
        authority_boundary_status: str = "not_checked"
        authority_boundary_data: Dict[str, Any] = {}
        quasi_platform_state_boundary_status: str = "not_checked"
        quasi_platform_state_boundary_data: Dict[str, Any] = {}
        phase_status = PhaseStatus.OK
        strict_authority = os.environ.get("GALAXY_STRICT_AUTHORITY_CHECK", "").lower() in (
            "1", "true", "yes"
        )
        try:
            from core.center_authority_boundary import (
                evaluate_center_authority_boundary,
                CenterAuthorityBoundaryReport,
            )
            boundary_report: CenterAuthorityBoundaryReport = evaluate_center_authority_boundary()
            authority_boundary_data = {
                "all_domains_intact": boundary_report.all_domains_intact,
                "degraded_domains": boundary_report.degraded_domains,
                "report_id": boundary_report.report_id,
            }
            if boundary_report.all_domains_intact:
                authority_boundary_status = "intact"
                logger.info(
                    "[Phase 7] V6 center authority boundary: INTACT — "
                    "all four authority domains verified."
                )
            else:
                authority_boundary_status = "degraded"
                if strict_authority:
                    phase_status = PhaseStatus.FAILED
                    logger.error(
                        "[Phase 7] V6 center authority boundary FAILED "
                        "(GALAXY_STRICT_AUTHORITY_CHECK=1): %s",
                        boundary_report.degraded_domains,
                    )
                else:
                    phase_status = PhaseStatus.DEGRADED
                    logger.warning(
                        "[Phase 7] V6 center authority boundary DEGRADED: %s",
                        boundary_report.degraded_domains,
                    )
                detail = (
                    f"{detail} | authority_boundary={'FAILED' if strict_authority else 'DEGRADED'} "
                    f"degraded_domains={boundary_report.degraded_domains}"
                )
        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            authority_boundary_status = "error"
            authority_boundary_data = {"error": str(exc)}
            logger.debug("[Phase 7] V6 center authority boundary check skipped — %s", exc)

        # PR-14V2 runtime extension: quasi-platform state integrity assertion.
        # Keep this in startup/readiness guard layer (not hot request path).
        try:
            from core.bounded_subject_platform_boundary import (
                build_quasi_platform_runtime_assertion_report,
            )

            quasi_platform_state_boundary_data = build_quasi_platform_runtime_assertion_report()
            if bool(quasi_platform_state_boundary_data.get("intact")):
                quasi_platform_state_boundary_status = "intact"
                logger.info(
                    "[Phase 7] Quasi-platform boundary assertion: INTACT — "
                    "canonical center / bounded subject / outward consumption "
                    "boundaries verified."
                )
            else:
                quasi_platform_state_boundary_status = "degraded"
                if strict_authority:
                    phase_status = PhaseStatus.FAILED
                    logger.error(
                        "[Phase 7] Quasi-platform boundary assertion FAILED "
                        "(GALAXY_STRICT_AUTHORITY_CHECK=1): %s",
                        quasi_platform_state_boundary_data.get("violations"),
                    )
                elif phase_status != PhaseStatus.FAILED:
                    phase_status = PhaseStatus.DEGRADED
                    logger.warning(
                        "[Phase 7] Quasi-platform boundary assertion DEGRADED: %s",
                        quasi_platform_state_boundary_data.get("violations"),
                    )
                detail = (
                    f"{detail} | quasi_platform_boundary="
                    f"{'FAILED' if strict_authority else 'DEGRADED'} "
                    f"violations={quasi_platform_state_boundary_data.get('violations')}"
                )
        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            quasi_platform_state_boundary_status = "error"
            quasi_platform_state_boundary_data = {"error": str(exc)}
            logger.debug(
                "[Phase 7] Quasi-platform boundary assertion check skipped — %s",
                exc,
            )

        return PhaseResult(
            phase=StartupPhase.READINESS_SUMMARY,
            status=phase_status,
            detail=detail,
            data={
                "readiness": summary.readiness.value,
                "system_mode": summary.system_mode,
                "authority_boundary_status": authority_boundary_status,
                "authority_boundary": authority_boundary_data,
                "quasi_platform_state_boundary_status": quasi_platform_state_boundary_status,
                "quasi_platform_state_boundary": quasi_platform_state_boundary_data,
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
