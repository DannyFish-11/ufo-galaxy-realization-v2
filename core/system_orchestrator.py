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
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.Orchestrator")

# ---------------------------------------------------------------------------
# Authority sentinel — used by validate_runtime.py and CI guardrails
# ---------------------------------------------------------------------------

SYSTEM_ORCHESTRATOR_AUTHORITY: str = "main.py:SYSTEM_ORCHESTRATOR — canonical staged bring-up contract (PR-2)"

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

    LOAD_CONFIG = 1  # Phase 1 — Load unified configuration baseline
    RESOLVE_MODE = 2  # Phase 2 — Resolve current system mode
    ENV_CHECKS = 3  # Phase 3 — Environment / bootstrap checks
    BACKGROUND_SUBSYSTEMS = 4  # Phase 4 — Background subsystem bring-up hooks
    RUNTIME_SUBJECT = 5  # Phase 5 — Runtime subject bring-up hooks
    DESKTOP_SURFACE = 6  # Phase 6 — Desktop surface bring-up hooks
    READINESS_SUMMARY = 7  # Phase 7 — Final readiness summary


#: 阶段的中文名 —— **唯一出处**。控制台要打这些阶段的进度（见 ``main.py`` 的
#: ``_run_orchestrator_preflight``），名字就只能从这里取，不许在入口再抄一份。
PHASE_LABELS: Dict["StartupPhase", str] = {}

#: 哪些阶段【会长时间不吭声】，以及为什么。
#:
#: 这不是装饰。Phase 6 会同步 ``subprocess.run([npm, "install"], capture_output=True)``：
#: npm 自己的进度输出被 capture 吃掉，本模块的 ``logger.info`` 又只进
#: ``logs/lumiv.log``（``main.py`` 的控制台 handler 是 WARNING 级），于是首次启动
#: 时"环境检查"之后控制台可以整整几分钟一个字都没有 —— 用户只能理解成卡死了。
#: 入口拿这里的理由，在阶段【开始前】先打一行，把沉默解释掉。
PHASE_MAY_BLOCK: Dict["StartupPhase", str] = {}


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


PHASE_LABELS.update(
    {
        StartupPhase.LOAD_CONFIG: "载入配置",
        StartupPhase.RESOLVE_MODE: "解析系统模式",
        StartupPhase.ENV_CHECKS: "环境判据",
        StartupPhase.BACKGROUND_SUBSYSTEMS: "后台子系统",
        StartupPhase.RUNTIME_SUBJECT: "运行时主体",
        StartupPhase.DESKTOP_SURFACE: "桌面表面",
        StartupPhase.READINESS_SUMMARY: "就绪汇总",
    }
)

PHASE_MAY_BLOCK.update(
    {
        StartupPhase.DESKTOP_SURFACE: "首次要装 Electron 前端依赖(npm install),可能数分钟;已装好则秒过",
    }
)


@dataclass
class PhaseResult:
    """Outcome of a single startup phase.

    ``detail`` 与 ``said`` 是**刻意分开**的两件事：

    - ``detail`` —— 给机器和日志看的证据串。判据会在里面 grep
      ``GALAXY_SKIP_DESKTOP_SURFACE`` / ``authority_boundary=`` /
      ``required_nats_unreachable`` 这类锚点，所以它必须稳定、可搜、不翻译。
    - ``said``   —— 给**人**看的一句话，打在控制台上。屏幕上原本全是
      ``runtime subject authority chain importable`` 这种只有写的人看得懂的
      英文碎片；把它翻译在显示层又会变成"猜字符串"，所以由**产出结果的那一处**
      自己说一句人话。留空则显示层回退到 ``detail``（宁可露出英文，也不许瞎编）。
    """

    phase: StartupPhase
    status: PhaseStatus
    detail: str = ""
    said: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True when phase completed without hard failure."""
        return self.status in (PhaseStatus.OK, PhaseStatus.DEGRADED, PhaseStatus.SKIPPED)

    def __str__(self) -> str:
        return f"[{self.phase.name}] {self.status.name}" + (f" — {self.detail}" if self.detail else "")


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


# ── Phase 6 装前端依赖的等待上限(秒) ──────────────────────────────────────
#
# 一处权威:两处 subprocess.run 和那条超时降级文案都从这里取,不各写各的数。
#
# 为什么要能调小:这两个数原本硬写成 120/300,而调它的测试跑在 pytest 的
# 120 秒上限里 —— **内层不小于外层**,于是 `npm install timed out after 120s`
# 那条优雅降级永远到不了,只能被外层硬超时打断(看起来接上了,其实没有)。
# 现在默认值不变(真机行为一个字没改),但环境变量能把内层压到外层以下,
# 那条降级路径因此变成可真正走到、可被测试盯住的路径。
NPM_INSTALL_TIMEOUT_S = 120.0
# 镜像重试给得更宽(国内换源本来就慢),但跟着上面的开关一起缩。
NPM_INSTALL_MIRROR_TIMEOUT_S = 300.0


def npm_install_timeouts() -> Tuple[float, float]:
    """取(首次, 镜像重试)两个等待上限,**每次调用现读环境变量**。

    不在模块级把 env 读死:那样值会冻在 import 那一刻,谁先 import 谁说了算,
    调用方再设环境变量也没用 —— 又是一种"看起来能调,其实调不动"。
    """

    def _read(name: str, default: float) -> float:
        raw = os.environ.get(name, "").strip()
        if not raw:
            return default
        try:
            val = float(raw)
        except ValueError:
            logger.warning("%s=%r 不是数字,按默认 %gs 走。", name, raw, default)
            return default
        if val <= 0:
            logger.warning("%s=%r 不是正数,按默认 %gs 走。", name, raw, default)
            return default
        return val

    primary = _read("GALAXY_NPM_INSTALL_TIMEOUT_S", NPM_INSTALL_TIMEOUT_S)
    mirror = _read("GALAXY_NPM_INSTALL_MIRROR_TIMEOUT_S", primary * 2.5)
    return primary, mirror


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
            strict_preflight = os.environ.get(STRICT_PREFLIGHT_ENV_VAR, "").lower() in ("1", "true", "yes")
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
        logger.info("[启动·配置] Loading unified configuration …")
        try:
            from core.unified_config import get_config

            cfg = get_config()
            detail = "unified config loaded"
            said = "配置已载入"
            if hasattr(cfg, "get_status_dict"):
                status_d = cfg.get_status_dict()
                llm_count = sum(1 for v in status_d.get("llm_apis", {}).values() if v)
                detail = f"unified config loaded — {llm_count} LLM API(s) configured"
                said = f"配置已载入,已填好 {llm_count} 家大模型的密钥"
            return PhaseResult(
                phase=StartupPhase.LOAD_CONFIG,
                status=PhaseStatus.OK,
                detail=detail,
                said=said,
                data={"config_loaded": True},
            )
        except Exception as exc:
            logger.warning("[启动·配置] Config load degraded: %s", exc)
            return PhaseResult(
                phase=StartupPhase.LOAD_CONFIG,
                status=PhaseStatus.DEGRADED,
                detail=f"config load degraded — {exc}",
                said=f"配置没能完整载入,先按默认值跑:{exc}",
            )

    def _run_phase_2_resolve_mode(self) -> PhaseResult:
        """Phase 2 — Resolve current system mode."""
        import os

        logger.info("[启动·模式] Resolving system mode …")
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
        logger.info("[启动·模式] %s", detail)
        _scope = "可用其他设备" if cross_device else "只用本机"
        _bus = "消息总线已开" if nats_enabled else "不用消息总线"
        return PhaseResult(
            phase=StartupPhase.RESOLVE_MODE,
            status=PhaseStatus.OK,
            detail=detail,
            said=f"按 {mode} 跑 —— {_scope},{_bus}",
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
        logger.info("[启动·环境检查] Running environment / bootstrap checks …")
        issues: List[str] = []
        has_critical_failure = False
        try:
            from core.config_preflight import ConfigPreflightError, run_preflight  # noqa: F401

            report = run_preflight(dry_run=True)  # collect findings without raising
            if not report.ok:
                issues.append(f"preflight: {len(report.critical_findings)} CRITICAL finding(s)")
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
                said="环境有必须先修的问题:" + "; ".join(issues),
            )
        if issues:
            return PhaseResult(
                phase=StartupPhase.ENV_CHECKS,
                status=PhaseStatus.DEGRADED,
                detail="; ".join(issues),
                said="环境能跑,但有欠缺:" + "; ".join(issues),
            )
        return PhaseResult(
            phase=StartupPhase.ENV_CHECKS,
            status=PhaseStatus.OK,
            detail="environment checks passed",
            said="环境判据全部通过",
        )

    def _run_phase_4_background_subsystems(self) -> PhaseResult:
        """Phase 4 — Background subsystem readiness checks (verifiable).

        This phase keeps orchestration ownership in ``main.py`` while performing
        low-cost, externally explainable checks that verify the runtime can route
        and execute through canonical surfaces.
        """
        logger.info("[启动·子系统] Verifying background subsystem readiness …")
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
            diagnostics["checks"]["nats_posture_assertion_ok"] = bool(nats_posture.get("assertion_ok", True))
            diagnostics["nats_posture"] = nats_posture
            if not nats_posture.get("assertion_ok", True):
                reason = nats_posture.get("violation_reason") or "nats_posture_violation_unknown_reason"
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
            logger.debug("[启动·子系统] Multi-device session recovery skipped — %s", exc)

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
            logger.warning("[启动·子系统] Startup recovery skipped — %s", exc)

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
            logger.debug("[启动·子系统] Lifecycle registry restore skipped — %s", exc)

        if hard_failures:
            parts: List[str] = []
            parts.append("hard_failures=" + ",".join(hard_failures))
            if issues:
                parts.append("degraded_issues=" + ",".join(issues))
            return PhaseResult(
                phase=StartupPhase.BACKGROUND_SUBSYSTEMS,
                status=PhaseStatus.FAILED,
                detail="background readiness failed — " + "; ".join(parts),
                said="后台子系统没起来:" + "; ".join(parts),
                data=diagnostics,
            )

        if issues:
            return PhaseResult(
                phase=StartupPhase.BACKGROUND_SUBSYSTEMS,
                status=PhaseStatus.DEGRADED,
                detail="background readiness degraded — " + "; ".join(issues),
                said="后台子系统能用,但有欠缺:" + "; ".join(issues),
                data=diagnostics,
            )

        return PhaseResult(
            phase=StartupPhase.BACKGROUND_SUBSYSTEMS,
            status=PhaseStatus.OK,
            detail="background readiness verified for canonical routing",
            said="后台子系统就绪,主链路由可用",
            data=diagnostics,
        )

    def _run_phase_5_runtime_subject(self) -> PhaseResult:
        """Phase 5 — Runtime subject bring-up hooks.

        Runtime subject: DesktopPresenceRuntime → OpenClawd.
        This phase confirms the subject authority chain is importable and
        will be activated during the async bring-up driven by Phase 4.
        """
        logger.info("[启动·运行时] Beginning runtime subject bring-up hooks …")
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
                said="运行时主体有缺件:" + "; ".join(issues),
            )
        return PhaseResult(
            phase=StartupPhase.RUNTIME_SUBJECT,
            status=PhaseStatus.OK,
            detail="runtime subject authority chain importable",
            said="运行时主体就绪,权威链完整",
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
        logger.info("[启动·桌面壳] Desktop surface bring-up (Electron three-state GUI) ...")

        # PR-ELECTRON-DEDUP: 跨启动路径共享同一把 .electron.pid 锁——本 Phase 常常是
        # 最先发起桌面壳启动的路径(网关甚至还没开始监听端口),之前完全不检查/不写
        # 这把锁,导致 unified_launcher 侧再次尝试启动时重复起一个 Electron 子进程
        # (npm install/npm start 各跑两遍),且谁先抢到 Electron 自身的单实例锁完全
        # 随机、可能是没被注入正确网关端口的那一个。这里先查锁,已有存活实例则
        # 直接跳过(不做任何 npm 探测/安装工作)。
        # 无头部署与测试:显式关掉桌面壳这一阶段。
        #
        # 这个阶段在 electron 包不完整时会真的去跑 `npm install`(联网、子进程),
        # 而 tests/test_batch_pr2_startup_orchestrator.py 里有四条测试直接调
        # run_startup_sequence(),于是单元测试会发起网络安装 —— CI 上并发一高就
        # 撞穿 pytest 那 120 秒。等待上限见 NPM_INSTALL_TIMEOUT_S(可用
        # GALAXY_NPM_INSTALL_TIMEOUT_S 调小,让内层严格小于外层,优雅降级才到得了)。
        #
        # 对无头/服务端部署这个开关本来也该有:那种机器上没人看 GUI,不该为它装
        # 一套 Electron 依赖。
        if os.environ.get("GALAXY_SKIP_DESKTOP_SURFACE", "").lower() in ("1", "true", "yes"):
            return PhaseResult(
                phase=StartupPhase.DESKTOP_SURFACE,
                status=PhaseStatus.DEGRADED,
                detail="Desktop surface skipped (GALAXY_SKIP_DESKTOP_SURFACE)",
                said="按 GALAXY_SKIP_DESKTOP_SURFACE 的要求跳过了桌面壳",
            )

        from core.electron_launch_guard import already_running, resolve_gateway_port, write_lock

        if already_running():
            return PhaseResult(
                phase=StartupPhase.DESKTOP_SURFACE,
                status=PhaseStatus.OK,
                detail="Electron GUI already running (started by another launch path)",
                said="桌面壳已经在跑了(别的启动路径先拉起来的)",
            )

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        electron_dir = os.path.join(project_root, "electron")

        # Check prerequisites
        if not os.path.isdir(electron_dir):
            return PhaseResult(
                phase=StartupPhase.DESKTOP_SURFACE,
                status=PhaseStatus.DEGRADED,
                detail="electron/ directory not found -- GUI not available",
                said="找不到 electron/ 目录,这次没有桌面壳",
            )

        # 预检 Node.js / npm 可用性（在调用 npm install 前主动探测，
        # 避免 FileNotFoundError 导致误导性错误信息 "Node.js not installed"）
        import shutil

        node_path = shutil.which("node")
        npm_path = shutil.which("npm")
        logger.debug("[启动·桌面壳] Node.js detection — node=%s, npm=%s", node_path, npm_path)

        if not node_path:
            return PhaseResult(
                phase=StartupPhase.DESKTOP_SURFACE,
                status=PhaseStatus.DEGRADED,
                detail="Electron GUI skipped (Node.js not installed or not in PATH)",
                said="跳过桌面壳:没装 Node.js,或它不在 PATH 里",
            )

        # Check if node_modules exists AND electron 包完整(不能只看目录存在——
        # 重新克隆/中断安装的残局里 .bin 存根在、electron/cli.js 缺失,直接拉起
        # 必然 "Cannot find module ...electron\cli.js" 崩溃;见
        # core.electron_launch_guard.electron_package_intact 的说明)。
        from core.electron_launch_guard import electron_package_intact

        node_modules = os.path.join(electron_dir, "node_modules")
        if not os.path.isdir(node_modules) or not electron_package_intact(electron_dir):
            if not npm_path:
                return PhaseResult(
                    phase=StartupPhase.DESKTOP_SURFACE,
                    status=PhaseStatus.DEGRADED,
                    detail="Electron GUI skipped (npm not in PATH — Node.js installed but npm missing)",
                    said="跳过桌面壳:装了 Node.js 但 PATH 里找不到 npm",
                )
            # 首次(或依赖不完整)先【安静地装】,不要在装之前就抛一条像"报错"的
            # WARNING —— 真机反馈:启动一上来先喊"依赖缺失或不完整"、把用户吓一跳,
            # 紧接着 npm 却报 "up to date"(其实好好的)。这里降为中性 INFO、措辞改成
            # "正在准备/补齐",只有 npm install 真失败(下面的分支)才升级为告警。
            _first_install = not os.path.isdir(node_modules)
            _npm_timeout, _npm_mirror_timeout = npm_install_timeouts()
            logger.info(
                "[启动·桌面壳] %s桌面前端依赖(npm install，首次可能数分钟)…",
                "首次准备" if _first_install else "补齐",
            )
            try:
                # Windows 子进程默认按 cp1252 解码,npm 的 UTF-8 输出会让读线程
                # UnicodeDecodeError 崩掉、stderr 变 None——显式 UTF-8 + replace。
                npm_result = subprocess.run(
                    [npm_path, "install"],
                    cwd=electron_dir,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=_npm_timeout,
                )
                if npm_result.returncode != 0:
                    # 官方 registry 网络失败(国内常见)→ npmmirror 镜像重试一次
                    _err_txt = npm_result.stderr or npm_result.stdout or ""
                    if any(
                        k in _err_txt
                        for k in (
                            "ETIMEDOUT",
                            "ECONNRESET",
                            "ECONNREFUSED",
                            "EAI_AGAIN",
                            "network",
                            "socket",
                            "TLS",
                            "fetch failed",
                        )
                    ):
                        logger.warning("[启动·桌面壳] npm 官方源失败,改用 npmmirror 镜像重试…")
                        npm_result = subprocess.run(
                            [npm_path, "install", "--registry=https://registry.npmmirror.com"],
                            cwd=electron_dir,
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            timeout=_npm_mirror_timeout,
                        )
                if npm_result.returncode != 0:
                    return PhaseResult(
                        phase=StartupPhase.DESKTOP_SURFACE,
                        status=PhaseStatus.DEGRADED,
                        detail=f"npm install failed: {(npm_result.stderr or '')[:200]}",
                        said=f"前端依赖没装上(npm install 失败):{(npm_result.stderr or '')[:120]}",
                    )
            except subprocess.TimeoutExpired:
                return PhaseResult(
                    phase=StartupPhase.DESKTOP_SURFACE,
                    status=PhaseStatus.DEGRADED,
                    detail=f"npm install timed out after {_npm_timeout:g}s",
                    said=f"装前端依赖超时({_npm_timeout:g} 秒没装完),这次先不开桌面壳",
                )

        # 拉起前核实到【运行时二进制】——真机根因("依赖残缺后补齐"仍闪退循环):
        # electron 包目录已存在时 npm install 会【跳过 postinstall】,缺失的
        # dist/electron.exe 永远补不回来,electron 启动即打印 "Electron failed to
        # install correctly" 退出。repair_electron_binary 直接跑包自带 install.js
        # (官方源失败换 npmmirror 镜像)补二进制;仍失败则降级并给出可照抄执行的
        # 确切修复指令,而不是拉起一个必然立即退出的进程进崩溃循环。
        if not electron_package_intact(electron_dir):
            from core.electron_launch_guard import (
                electron_binary_fix_hint,
                repair_electron_binary,
            )

            if not repair_electron_binary(electron_dir):
                return PhaseResult(
                    phase=StartupPhase.DESKTOP_SURFACE,
                    status=PhaseStatus.DEGRADED,
                    detail=electron_binary_fix_hint("electron"),
                    said="Electron 运行时二进制没补上,按提示手动修一次即可:" + electron_binary_fix_hint("electron"),
                )

        # 拉起用的必须是 shutil.which 解析出来的**绝对路径**,不能是裸 "npm"。
        # 真机实证(同一次启动里自相矛盾的两行):Phase 0 打了 `✓ npm`,Phase 6 却报
        # `DEGRADED — npm not found`。根因是 Windows 上 npm 实际叫 `npm.cmd`,
        # 而 CreateProcess **不套用 PATHEXT** —— 裸 "npm" 必然 FileNotFoundError,
        # 于是被下面的 except 判成"没装 Node.js",给出一个完全错误的诊断。
        # 上面 npm install 那两处早就用的是 npm_path,只有这里漏了。
        if not npm_path:
            return PhaseResult(
                phase=StartupPhase.DESKTOP_SURFACE,
                status=PhaseStatus.DEGRADED,
                detail="Electron GUI skipped (npm not in PATH — Node.js installed but npm missing)",
                said="跳过桌面壳:装了 Node.js 但 PATH 里找不到 npm",
            )

        # Launch Electron as detached subprocess
        try:
            env = os.environ.copy()
            env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")
            # 同步真实网关端口给 Electron,避免 --port 覆盖时"赢"下单实例锁的这个
            # 实例仍连默认 9000,导致面板/感知帧全部 fetch 到错误端口(参见
            # core/electron_launch_guard.py 顶部说明)。
            env["GALAXY_GATEWAY_PORT"] = str(resolve_gateway_port())
            env.setdefault("PORT", env["GALAXY_GATEWAY_PORT"])

            # Use shell=False for security; npm start will run electron .
            process = subprocess.Popen(
                [npm_path, "start"],
                cwd=electron_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                # Detached so Electron survives if Python parent exits.
                # (POSIX: setsid via start_new_session; ignored on Windows.)
                start_new_session=True if sys.platform != "win32" else False,
            )
            write_lock(process.pid)

            # Start a background thread to drain stdout (prevents pipe buffer fill)
            threading.Thread(
                target=self._drain_electron_output,
                args=(process,),
                daemon=True,
                name="ElectronOutputDrainer",
            ).start()

            logger.info("[启动·桌面壳] Electron GUI launched (pid=%d)", process.pid)
            return PhaseResult(
                phase=StartupPhase.DESKTOP_SURFACE,
                status=PhaseStatus.OK,
                detail=f"Electron GUI launched (pid={process.pid})",
                said=f"桌面壳已拉起(进程号 {process.pid})",
                data={"electron_pid": process.pid},
            )

        except FileNotFoundError as exc:
            # 走到这里说明 shutil.which 找到的那个 npm 路径**自己**起不来
            # (被删/权限/损坏),而不是"没装 Node.js" —— 如实说出真正缺的东西,
            # 别再给用户一个去装 Node.js 的错误指引(它明明装着)。
            return PhaseResult(
                phase=StartupPhase.DESKTOP_SURFACE,
                status=PhaseStatus.DEGRADED,
                detail=f"无法执行 npm({npm_path}): {exc}",
                said=f"npm 跑不起来({npm_path}):{exc}",
            )
        except Exception as exc:
            return PhaseResult(
                phase=StartupPhase.DESKTOP_SURFACE,
                status=PhaseStatus.DEGRADED,
                detail=f"Electron launch failed: {exc}",
                said=f"桌面壳启动失败:{exc}",
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
        logger.info("[启动·就绪汇总] Producing final readiness summary …")
        detail = (
            f"readiness={summary.readiness.value}, "
            f"phases_ok={sum(1 for r in summary.phase_results if r.ok)}/"
            f"{len(summary.phase_results)}"
        )
        logger.info("[启动·就绪汇总] %s", detail)

        # V6 center authority boundary integrity check — boundary / startup layer
        authority_boundary_status: str = "not_checked"
        authority_boundary_data: Dict[str, Any] = {}
        quasi_platform_state_boundary_status: str = "not_checked"
        quasi_platform_state_boundary_data: Dict[str, Any] = {}
        phase_status = PhaseStatus.OK
        strict_authority = os.environ.get("GALAXY_STRICT_AUTHORITY_CHECK", "").lower() in ("1", "true", "yes")
        try:
            from core.center_authority_boundary import (
                CenterAuthorityBoundaryReport,
                evaluate_center_authority_boundary,
            )

            boundary_report: CenterAuthorityBoundaryReport = evaluate_center_authority_boundary()
            authority_boundary_data = {
                "all_domains_intact": boundary_report.all_domains_intact,
                "degraded_domains": boundary_report.degraded_domains,
                "report_id": boundary_report.report_id,
            }
            if boundary_report.all_domains_intact:
                authority_boundary_status = "intact"
                logger.info("[Phase 7] V6 center authority boundary: INTACT — " "all four authority domains verified.")
            else:
                authority_boundary_status = "degraded"
                if strict_authority:
                    phase_status = PhaseStatus.FAILED
                    logger.error(
                        "[Phase 7] V6 center authority boundary FAILED " "(GALAXY_STRICT_AUTHORITY_CHECK=1): %s",
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
            logger.debug("[启动·就绪汇总] V6 center authority boundary check skipped — %s", exc)

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
                        "[Phase 7] Quasi-platform boundary assertion FAILED " "(GALAXY_STRICT_AUTHORITY_CHECK=1): %s",
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

        _all_n = len(summary.phase_results)
        _ok_n = sum(1 for r in summary.phase_results if r.status == PhaseStatus.OK)
        _degraded_n = sum(1 for r in summary.phase_results if r.status == PhaseStatus.DEGRADED)
        _failed_n = sum(1 for r in summary.phase_results if r.status == PhaseStatus.FAILED)
        _verdict = {
            OrchestratorReadiness.READY: "一切就绪",
            OrchestratorReadiness.DEGRADED: "可以用,有降级",
            OrchestratorReadiness.FAILED: "有阶段失败",
        }.get(summary.readiness, summary.readiness.value)
        _parts = [f"{_ok_n}/{_all_n} 个阶段正常"]
        if _degraded_n:
            _parts.append(f"{_degraded_n} 个降级")
        if _failed_n:
            _parts.append(f"{_failed_n} 个失败")
        if authority_boundary_status == "degraded":
            _parts.append("权威边界降级")
        if quasi_platform_state_boundary_status == "degraded":
            _parts.append("平台态边界降级")
        _said = f"{_verdict} —— " + "、".join(_parts)

        return PhaseResult(
            phase=StartupPhase.READINESS_SUMMARY,
            status=phase_status,
            detail=detail,
            said=_said,
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

    def run_startup_sequence(
        self,
        *,
        on_phase: Optional[Callable[[StartupPhase, Optional["PhaseResult"]], None]] = None,
    ) -> StartupSummary:
        """Execute all startup phases in order and return a :class:`StartupSummary`.

        Phases run sequentially.  If a phase returns ``FAILED`` and
        ``continue_on_failure`` is ``False`` (the default), remaining phases
        are marked ``SKIPPED``.

        Extra hooks registered via :meth:`register_hook` run immediately after
        the built-in logic for each phase and can supplement or override the
        default result.

        Args:
            on_phase: 可选的**只读旁观者**，用来把进度实时交出去。每个阶段调用两次：
                开始前 ``(phase, None)``，结束后 ``(phase, result)``。

                有这个参数是因为本方法此前把六个阶段【一口气跑完才返回】，而中间
                的进展只有 ``logger.info``（进 ``logs/lumiv.log``，控制台 handler
                是 WARNING 级）。于是 ``main.py`` 打完 "[Phase 1] 系统预检" 之后，
                控制台在 Phase 6 跑 ``npm install`` 期间可以几分钟毫无输出 —— 看起来
                就是卡死。旁观者让入口能在【阶段发生时】就打出来。

                它**不能改变任何结果**（返回值被忽略），抛异常也只记一条 warning：
                一个显示用的回调绝不允许把启动带崩。
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

        def _notify(phase: StartupPhase, result: Optional[PhaseResult]) -> None:
            if on_phase is None:
                return
            try:
                on_phase(phase, result)
            except Exception as exc:  # noqa: BLE001 — 显示层绝不能挡启动
                logger.warning("on_phase observer raised for %s: %s", phase.name, exc)

        for phase, runner in _phase_runners:
            _notify(phase, None)
            if failed and not self.continue_on_failure:
                result = PhaseResult(
                    phase=phase,
                    status=PhaseStatus.SKIPPED,
                    detail="skipped due to earlier failure",
                    said="前面的阶段失败了,这一步跳过",
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
            _notify(phase, result)

            if result.status == PhaseStatus.FAILED:
                failed = True

        # Extract system_mode from Phase 2 result
        for r in summary.phase_results:
            if r.phase == StartupPhase.RESOLVE_MODE and r.data.get("system_mode"):
                summary.system_mode = r.data["system_mode"]
                break

        # Phase 7 — readiness summary (always runs)
        _notify(StartupPhase.READINESS_SUMMARY, None)
        summary_result = self._run_phase_7_readiness_summary(summary)
        summary.add_result(summary_result)
        _notify(StartupPhase.READINESS_SUMMARY, summary_result)

        return summary
