#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/deployment_baseline.py
============================
PR-531: Deployment Baseline — Deployment / Environment Convergence and
Minimum Runtime Baseline Enforcement.

This module is the **deployment baseline authority** for the Galaxy runtime.
It provides code-level validation and enforceable checks for the minimum
runtime model rather than relying on documentation-only alignment.

Problem addressed
-----------------
After PRs #506–#530 the internal canonical pipeline is well-defined.
However, the minimum runtime baseline required for core execution is not
enforceable in code:

- The boundary between development, runtime, and deployment expectations is
  ambiguous in several places.
- There is no single checkable object that says "the system meets the minimum
  core runtime baseline."
- Environment-level split assumptions (dev vs. runtime vs. production) are not
  consistently encoded.

This module provides:

1. **DeploymentEnvironment enum** — three canonical environment tiers
   (``CORE_RUNTIME``, ``STANDARD_DEV``, ``FULL_PRODUCTION``) that map directly
   to the existing startup tier model.

2. **DeploymentBaselineRequirement** — a single checkable requirement with
   a machine-readable pass/fail outcome.

3. **DeploymentBaselineRuntime** — singleton that evaluates and caches
   baseline checks, making the current deployment baseline posture queryable.

4. **check_runtime_baseline()** — primary entry point for preflight and
   CI/operator validation.

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────────┐
    │  DEPLOYMENT / CI / LAUNCHER LAYER                               │
    │  scripts/validate_runtime.py  ·  launcher/bootstrap.py          │
    └────────────────────────────┬─────────────────────────────────────┘
                                 ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │  DEPLOYMENT BASELINE LAYER  (this module, Layer 15)             │
    │                                                                  │
    │  DeploymentEnvironment enum                                     │
    │  DeploymentBaselineRequirement dataclass                        │
    │  DeploymentBaselineRuntime singleton                            │
    │  check_runtime_baseline() → DeploymentBaselineReport           │
    │                                                                  │
    │  Reads from:                                                    │
    │    • StartupTierModel — tier/readiness baseline                 │
    │    • CallableNodeBaseline — callable-class baseline             │
    │    • ConfigPreflight — environment / config validation          │
    └──────────────────────────────────────────────────────────────────┘

Public API
----------
Authority sentinels::

    DEPLOYMENT_BASELINE_AUTHORITY
    DEPLOYMENT_BASELINE_LAYER_POSITION
    DEPLOYMENT_BASELINE_CONVERGENCE_DEFINED

Policy sentinels::

    CORE_RUNTIME_MUST_BE_CHECKABLE_POLICY
    ENVIRONMENT_TIERS_MUST_MAP_TO_STARTUP_TIERS_POLICY

Enums::

    DeploymentEnvironment
    BaselineCheckStatus

Dataclasses::

    DeploymentBaselineRequirement
    DeploymentBaselineReport

Class::

    DeploymentBaselineRuntime
    get_deployment_baseline_runtime()
    reset_deployment_baseline_runtime()

Helpers::

    check_runtime_baseline(env) -> DeploymentBaselineReport
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.DeploymentBaseline")

PROJECT_ROOT = Path(__file__).parent.parent

# ===========================================================================
# Authority sentinels
# ===========================================================================

DEPLOYMENT_BASELINE_AUTHORITY: str = (
    "DEPLOYMENT_BASELINE::PR531_DEPLOYMENT_BASELINE_AUTHORITY_V1: "
    "core/deployment_baseline.py is the canonical authority for minimum "
    "runtime baseline enforcement.  Layer 15.  "
    "Use check_runtime_baseline() for preflight and CI validation."
)

DEPLOYMENT_BASELINE_LAYER_POSITION: int = 15

DEPLOYMENT_BASELINE_CONVERGENCE_DEFINED: str = (
    "DEPLOYMENT_BASELINE_CONVERGENCE_V1: "
    "Three convergent environment tiers — CORE_RUNTIME, STANDARD_DEV, "
    "FULL_PRODUCTION — map directly to the startup tier model (Core / Standard "
    "/ Full).  Baseline requirements for each tier are code-level checkable."
)

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

CORE_RUNTIME_MUST_BE_CHECKABLE_POLICY: str = (
    "CORE_RUNTIME_MUST_BE_CHECKABLE_V1: "
    "The minimum core runtime baseline MUST be expressible as a checkable "
    "pass/fail assertion in code.  Documentation-only alignment is not "
    "sufficient for the core execution path."
)

ENVIRONMENT_TIERS_MUST_MAP_TO_STARTUP_TIERS_POLICY: str = (
    "ENVIRONMENT_TIERS_MUST_MAP_TO_STARTUP_TIERS_V1: "
    "DeploymentEnvironment tiers MUST map 1:1 to the existing startup tier "
    "model (Core/Standard/Full).  A new deployment tier requires a "
    "corresponding startup tier definition — no orphaned env tiers."
)

# ===========================================================================
# Enums
# ===========================================================================


class DeploymentEnvironment(str, Enum):
    """Canonical deployment environment tiers.

    Maps 1:1 to startup tiers in :mod:`core.startup_tier_model`.
    """

    CORE_RUNTIME = "core_runtime"
    """Minimum canonical runtime — maps to StartupTier.Core."""

    STANDARD_DEV = "standard_dev"
    """Normal development/functional environment — maps to StartupTier.Standard."""

    FULL_PRODUCTION = "full_production"
    """Full production environment — maps to StartupTier.Full."""


class BaselineCheckStatus(str, Enum):
    """Status of a single baseline requirement check."""

    PASSED = "passed"
    FAILED = "failed"
    WARN = "warn"
    SKIPPED = "skipped"


# ===========================================================================
# Dataclasses
# ===========================================================================


@dataclass
class DeploymentBaselineRequirement:
    """A single checkable baseline requirement."""

    check_name: str
    """Short human-readable name for this requirement."""

    environment: DeploymentEnvironment
    """The deployment environment this requirement applies to."""

    status: BaselineCheckStatus = BaselineCheckStatus.SKIPPED
    detail: str = ""
    evaluated_at: float = field(default_factory=time.time)


@dataclass
class DeploymentBaselineReport:
    """Report from a full baseline evaluation for one environment tier."""

    environment: DeploymentEnvironment
    report_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    compiled_at: float = field(default_factory=time.time)
    authority: str = DEPLOYMENT_BASELINE_AUTHORITY

    requirements: List[DeploymentBaselineRequirement] = field(default_factory=list)

    passed_count: int = 0
    failed_count: int = 0
    warn_count: int = 0
    skipped_count: int = 0

    baseline_met: bool = False
    """True when all required checks pass (warnings are tolerated)."""

    summary_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "environment": self.environment.value,
            "report_id": self.report_id,
            "compiled_at": self.compiled_at,
            "authority": self.authority,
            "baseline_met": self.baseline_met,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "warn_count": self.warn_count,
            "skipped_count": self.skipped_count,
            "summary_notes": self.summary_notes,
            "requirements": [
                {
                    "check_name": r.check_name,
                    "environment": r.environment.value,
                    "status": r.status.value,
                    "detail": r.detail,
                }
                for r in self.requirements
            ],
        }


# ===========================================================================
# Baseline evaluation helpers
# ===========================================================================


def _check_startup_tier_model_importable(
    env: DeploymentEnvironment,
) -> DeploymentBaselineRequirement:
    req = DeploymentBaselineRequirement(
        check_name="startup_tier_model_importable",
        environment=env,
    )
    try:
        from core.startup_tier_model import (
            STARTUP_TIER_MODEL_AUTHORITY,
            TIER_CORE,
        )
        from launcher.node_startup import NodeSystemLauncher

        req.status = BaselineCheckStatus.PASSED
        req.detail = f"startup_tier_model importable; NodeSystemLauncher accessible"
    except Exception as exc:
        logger.debug("Fallback triggered: %s", exc)
        req.status = BaselineCheckStatus.FAILED
        req.detail = str(exc)[:200]
    return req


def _make_launcher() -> Any:
    """Return a lightweight NodeSystemLauncher for baseline checks."""
    import json as _json
    from unittest.mock import MagicMock as _MM
    from launcher.node_startup import NodeSystemLauncher

    ndj_path = PROJECT_ROOT / "node_dependencies.json"
    with open(ndj_path, "r", encoding="utf-8") as fh:
        ndj = _json.load(fh)
    service_manager = _MM()
    config = _MM()
    config.web_ui_port = 9000
    instance = NodeSystemLauncher.__new__(NodeSystemLauncher)
    instance.service_manager = service_manager
    instance.config = config
    instance.nodes_dir = PROJECT_ROOT / "nodes"
    instance.node_configs = ndj.get("nodes", {})
    return instance


def _check_callable_node_baseline(
    env: DeploymentEnvironment,
) -> DeploymentBaselineRequirement:
    req = DeploymentBaselineRequirement(
        check_name="callable_node_baseline_established",
        environment=env,
    )
    try:
        from core.callable_node_baseline import (
            CALLABLE_NODE_BASELINE_ESTABLISHED,
            CALLABLE_ARCHITECTURAL_CLASSES,
        )

        req.status = BaselineCheckStatus.PASSED
        req.detail = (
            f"callable_classes={len(CALLABLE_ARCHITECTURAL_CLASSES)}; "
            f"sentinel={CALLABLE_NODE_BASELINE_ESTABLISHED[:40]}..."
        )
    except Exception as exc:
        logger.debug("Fallback triggered: %s", exc)
        req.status = BaselineCheckStatus.FAILED
        req.detail = str(exc)[:200]
    return req


def _check_capability_registry_importable(
    env: DeploymentEnvironment,
) -> DeploymentBaselineRequirement:
    req = DeploymentBaselineRequirement(
        check_name="capability_registry_importable",
        environment=env,
    )
    try:
        from core.agent.capability_registry import (
            CapabilityRegistry,
            CAPABILITY_REGISTRY_IS_CANONICAL_TRUTH_SOURCE,
        )

        req.status = BaselineCheckStatus.PASSED
        req.detail = "CapabilityRegistry importable; canonical sentinel present"
    except Exception as exc:
        logger.debug("Fallback triggered: %s", exc)
        req.status = BaselineCheckStatus.FAILED
        req.detail = str(exc)[:200]
    return req


def _check_node_dependencies_json(
    env: DeploymentEnvironment,
) -> DeploymentBaselineRequirement:
    req = DeploymentBaselineRequirement(
        check_name="node_dependencies_json_valid",
        environment=env,
    )
    ndj_path = PROJECT_ROOT / "node_dependencies.json"
    try:
        import json

        with open(ndj_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        node_count = len(data.get("nodes", {}))
        req.status = BaselineCheckStatus.PASSED
        req.detail = f"node_dependencies.json valid; {node_count} node entries"
    except FileNotFoundError:
        req.status = BaselineCheckStatus.FAILED
        req.detail = f"node_dependencies.json not found at {ndj_path}"
    except Exception as exc:
        logger.debug("Fallback triggered: %s", exc)
        req.status = BaselineCheckStatus.FAILED
        req.detail = str(exc)[:200]
    return req


def _check_core_tier_non_empty(
    env: DeploymentEnvironment,
) -> DeploymentBaselineRequirement:
    req = DeploymentBaselineRequirement(
        check_name="core_tier_nodes_non_empty",
        environment=env,
    )
    try:
        from launcher.node_startup import NodeSystemLauncher

        launcher = _make_launcher()
        nodes = launcher.get_tier_nodes(NodeSystemLauncher.STARTUP_TIER_CORE)
        if nodes:
            req.status = BaselineCheckStatus.PASSED
            req.detail = f"{len(nodes)} Core-tier nodes present"
        else:
            req.status = BaselineCheckStatus.FAILED
            req.detail = "Core tier has zero nodes — cannot form minimum runtime"
    except Exception as exc:
        logger.debug("Fallback triggered: %s", exc)
        req.status = BaselineCheckStatus.FAILED
        req.detail = str(exc)[:200]
    return req


def _check_standard_tier_superset(
    env: DeploymentEnvironment,
) -> DeploymentBaselineRequirement:
    """Standard ⊇ Core invariant check."""
    req = DeploymentBaselineRequirement(
        check_name="standard_tier_superset_of_core",
        environment=env,
    )
    try:
        from launcher.node_startup import NodeSystemLauncher

        launcher = _make_launcher()
        core_nodes = set(launcher.get_tier_nodes(NodeSystemLauncher.STARTUP_TIER_CORE))
        std_nodes = set(launcher.get_tier_nodes(NodeSystemLauncher.STARTUP_TIER_STANDARD))
        if core_nodes.issubset(std_nodes):
            req.status = BaselineCheckStatus.PASSED
            req.detail = f"Standard({len(std_nodes)}) ⊇ Core({len(core_nodes)})"
        else:
            missing = core_nodes - std_nodes
            req.status = BaselineCheckStatus.FAILED
            req.detail = f"Standard tier missing Core nodes: {list(missing)[:5]}"
    except Exception as exc:
        logger.debug("Fallback triggered: %s", exc)
        req.status = BaselineCheckStatus.FAILED
        req.detail = str(exc)[:200]
    return req


def _check_outward_truth_importable(
    env: DeploymentEnvironment,
) -> DeploymentBaselineRequirement:
    req = DeploymentBaselineRequirement(
        check_name="outward_runtime_truth_importable",
        environment=env,
    )
    try:
        from core.outward_runtime_truth import (
            OUTWARD_RUNTIME_TRUTH_AUTHORITY,
            compile_outward_truth,
        )

        req.status = BaselineCheckStatus.PASSED
        req.detail = "outward_runtime_truth importable; compile_outward_truth callable"
    except Exception as exc:
        logger.debug("Fallback triggered: %s", exc)
        req.status = BaselineCheckStatus.FAILED
        req.detail = str(exc)[:200]
    return req


def _check_node_lifecycle_governor_importable(
    env: DeploymentEnvironment,
) -> DeploymentBaselineRequirement:
    req = DeploymentBaselineRequirement(
        check_name="node_lifecycle_governor_importable",
        environment=env,
    )
    try:
        from core.node_lifecycle_governor import (
            NODE_LIFECYCLE_GOVERNOR_AUTHORITY,
            get_node_lifecycle_governor,
        )

        gov = get_node_lifecycle_governor()
        req.status = BaselineCheckStatus.PASSED
        req.detail = "node_lifecycle_governor importable and singleton accessible"
    except Exception as exc:
        logger.debug("Fallback triggered: %s", exc)
        req.status = BaselineCheckStatus.FAILED
        req.detail = str(exc)[:200]
    return req


# ===========================================================================
# check_runtime_baseline()
# ===========================================================================

#: Required checks for each environment tier.
_ENV_CHECKS = {
    DeploymentEnvironment.CORE_RUNTIME: [
        _check_startup_tier_model_importable,
        _check_callable_node_baseline,
        _check_capability_registry_importable,
        _check_node_dependencies_json,
        _check_core_tier_non_empty,
        _check_outward_truth_importable,
        _check_node_lifecycle_governor_importable,
    ],
    DeploymentEnvironment.STANDARD_DEV: [
        _check_startup_tier_model_importable,
        _check_callable_node_baseline,
        _check_capability_registry_importable,
        _check_node_dependencies_json,
        _check_core_tier_non_empty,
        _check_standard_tier_superset,
        _check_outward_truth_importable,
        _check_node_lifecycle_governor_importable,
    ],
    DeploymentEnvironment.FULL_PRODUCTION: [
        _check_startup_tier_model_importable,
        _check_callable_node_baseline,
        _check_capability_registry_importable,
        _check_node_dependencies_json,
        _check_core_tier_non_empty,
        _check_standard_tier_superset,
        _check_outward_truth_importable,
        _check_node_lifecycle_governor_importable,
    ],
}


def check_runtime_baseline(
    env: DeploymentEnvironment = DeploymentEnvironment.CORE_RUNTIME,
) -> DeploymentBaselineReport:
    """Evaluate the deployment baseline for *env* and return a report.

    This is the primary entry point for preflight and CI validation.
    It runs all required checks for the given environment tier and returns
    a :class:`DeploymentBaselineReport` with pass/fail/warn per requirement.

    Parameters
    ----------
    env:
        The target deployment environment.  Defaults to
        :attr:`DeploymentEnvironment.CORE_RUNTIME` (minimum baseline).

    Returns
    -------
    DeploymentBaselineReport
        The evaluation report.  Inspect ``baseline_met`` for a binary
        pass/fail, or ``requirements`` for per-check detail.
    """
    check_fns = _ENV_CHECKS.get(env, _ENV_CHECKS[DeploymentEnvironment.CORE_RUNTIME])
    requirements: List[DeploymentBaselineRequirement] = []

    for fn in check_fns:
        try:
            req = fn(env)
        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            req = DeploymentBaselineRequirement(
                check_name=getattr(fn, "__name__", "unknown"),
                environment=env,
                status=BaselineCheckStatus.FAILED,
                detail=f"check function raised: {exc}",
            )
        requirements.append(req)

    passed = sum(1 for r in requirements if r.status == BaselineCheckStatus.PASSED)
    failed = sum(1 for r in requirements if r.status == BaselineCheckStatus.FAILED)
    warn = sum(1 for r in requirements if r.status == BaselineCheckStatus.WARN)
    skipped = sum(1 for r in requirements if r.status == BaselineCheckStatus.SKIPPED)

    notes: List[str] = []
    for r in requirements:
        if r.status == BaselineCheckStatus.FAILED:
            notes.append(f"FAILED: {r.check_name} — {r.detail}")

    report = DeploymentBaselineReport(
        environment=env,
        requirements=requirements,
        passed_count=passed,
        failed_count=failed,
        warn_count=warn,
        skipped_count=skipped,
        baseline_met=(failed == 0),
        summary_notes=notes,
    )

    get_deployment_baseline_runtime().record_report(report)
    logger.debug(
        "check_runtime_baseline(%s): passed=%d failed=%d baseline_met=%s",
        env.value,
        passed,
        failed,
        report.baseline_met,
    )
    return report


# ===========================================================================
# Runtime class
# ===========================================================================


class DeploymentBaselineRuntime:
    """Singleton that caches recent baseline evaluation reports."""

    _instance: Optional["DeploymentBaselineRuntime"] = None
    _class_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._reports: deque[DeploymentBaselineReport] = deque(maxlen=32)
        self._lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "DeploymentBaselineRuntime":
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton — **for testing only**."""
        with cls._class_lock:
            cls._instance = None

    def record_report(self, report: DeploymentBaselineReport) -> None:
        with self._lock:
            self._reports.append(report)

    def latest_report(
        self, env: Optional[DeploymentEnvironment] = None
    ) -> Optional[DeploymentBaselineReport]:
        with self._lock:
            if env is None:
                return self._reports[-1] if self._reports else None
            for report in reversed(list(self._reports)):
                if report.environment == env:
                    return report
            return None

    def all_reports(self) -> List[DeploymentBaselineReport]:
        with self._lock:
            return list(self._reports)


def get_deployment_baseline_runtime() -> DeploymentBaselineRuntime:
    """Return the process-level :class:`DeploymentBaselineRuntime` singleton."""
    return DeploymentBaselineRuntime.get_instance()


def reset_deployment_baseline_runtime() -> None:
    """Reset the singleton — **for testing only**."""
    DeploymentBaselineRuntime.reset()
