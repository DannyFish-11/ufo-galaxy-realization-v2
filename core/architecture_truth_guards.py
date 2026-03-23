#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.architecture_truth_guards — Architecture Guards for Canonical Truth Ownership
===================================================================================

PR-28 — Add architecture guards for canonical truth ownership and boundary invariants.

This module provides hard guards that make architectural regressions and
duplicate-truth paths easier to detect automatically.  It does *not* alter
execution logic; all checks are purely inspective.

## Why this module exists

After canonical state calibration (PR-24) and routing/policy unification
(PR-25–PR-27), the architecture can still regress if later code:

- bypasses canonical state structures
- reintroduces duplicate truth paths
- lets routers or provider adapters become final authorities
- lets shell/UI reconstruct decision truth independently
- blurs orchestration/substrate/control responsibilities

The guards here lock in the ownership contracts so that boundary drift is
caught automatically rather than during human code review.

## Invariants enforced

1. **Source registry is shell-owned** — ``DesktopPresenceRuntime`` owns
   ``_source_registry`` (``PerceptionSourceRegistry``); ``OpenClawd`` must
   *not* own one.

2. **OpenClawd is the final authority** — the ``subject_core`` layer must
   carry ``authority_role = "subject_decision_authority"`` and must be the
   sole owner of execution / model / fallback decisions.

3. **Canonical model supply is the capability truth layer** — routing
   decisions must derive from
   :class:`~core.model_topology.canonical_model_supply_state.CanonicalModelSupplyState`
   and must not be authored by lower-layer components such as
   ``CommandRouter`` or provider adapters.

4. **Desktop projection does not reconstruct truth** — projection artifacts
   must consume canonical control-plan artifacts; they must not contain
   independent capability registries or model selection logic.

5. **Execution / substrate layers do not self-promote** — ``CommandRouter``
   and other substrate components must claim ``"execution_substrate"`` only,
   never ``"subject_decision_authority"`` or ``"runtime_shell_authority"``.

6. **Orchestration is distinct from substrate and subject authority** —
   SwarmCoordinator / orchestration-layer outputs must carry
   ``"orchestration_layer"`` and must not claim substrate or subject-decision
   roles.

7. **No duplicate truth paths** — a snapshot must not contain multiple
   independent source registries or parallel model-capability dictionaries
   built by non-canonical components.

## Main API

:func:`run_canonical_truth_ownership_checks`
    Run invariants 1–4 against a plain dict snapshot.

:func:`run_boundary_invariant_checks`
    Run invariants 5–7 against a plain dict snapshot.

:func:`run_all_architecture_guards`
    Convenience wrapper that runs *all* checks and returns a single
    :class:`GuardReport`.

:class:`CanonicalTruthOwnershipGuard`
    Fine-grained static helpers for individual ownership assertions.

:class:`BoundaryInvariantGuard`
    Fine-grained static helpers for individual boundary assertions.

Usage in tests::

    from core.architecture_truth_guards import run_all_architecture_guards

    snapshot = {
        "runtime_shell": {
            "arch_layer_id": "runtime_shell",
            "authority_role": "runtime_shell_authority",
            "owns_source_registry": True,
        },
        "subject_core": {
            "arch_layer_id": "subject_core",
            "authority_role": "subject_decision_authority",
            "owns_source_registry": False,
            "is_final_model_authority": True,
        },
        "execution_substrate": {
            "arch_layer_id": "execution_substrate",
            "authority_role": "execution_substrate",
        },
        "orchestration_layer": {
            "arch_layer_id": "orchestration_layer",
            "authority_role": "orchestration_layer",
        },
        "projection": {
            "is_truth_reconstruction_layer": False,
            "sourced_from_canonical_plan": True,
        },
        "canonical_supply": {
            "is_canonical_supply_layer": True,
        },
    }
    report = run_all_architecture_guards(snapshot)
    assert report.passed, report.format_failures()
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ArchTruthGuards")

__all__ = [
    # Data types
    "GuardSeverity",
    "GuardFinding",
    "GuardReport",
    # Fine-grained guard classes
    "CanonicalTruthOwnershipGuard",
    "BoundaryInvariantGuard",
    # High-level entry points
    "run_canonical_truth_ownership_checks",
    "run_boundary_invariant_checks",
    "run_all_architecture_guards",
    # Constants
    "SHELL_OWNED_AUTHORITY_ROLES",
    "SUBJECT_CORE_AUTHORITY_ROLE",
    "EXECUTION_SUBSTRATE_ROLE",
    "ORCHESTRATION_LAYER_ROLE",
]

# ---------------------------------------------------------------------------
# Constants — canonical role identifiers
# ---------------------------------------------------------------------------

#: Authority roles that may ONLY be claimed by the runtime shell layer.
SHELL_OWNED_AUTHORITY_ROLES: frozenset[str] = frozenset(
    {"runtime_shell_authority"}
)

#: The single authority role that identifies OpenClawd / subject core.
SUBJECT_CORE_AUTHORITY_ROLE: str = "subject_decision_authority"

#: Authority role for execution-substrate components (CommandRouter etc.).
EXECUTION_SUBSTRATE_ROLE: str = "execution_substrate"

#: Authority role for orchestration-layer components (SwarmCoordinator etc.).
ORCHESTRATION_LAYER_ROLE: str = "orchestration_layer"

#: Roles that MUST NOT be claimed by substrate or orchestration components.
_ELEVATED_ROLES: frozenset[str] = frozenset(
    {
        "runtime_shell_authority",
        SUBJECT_CORE_AUTHORITY_ROLE,
    }
)

#: Roles that MUST NOT be claimed by projection / status consumers.
_AUTHORITY_ROLES_ALL: frozenset[str] = frozenset(
    {
        "runtime_shell_authority",
        SUBJECT_CORE_AUTHORITY_ROLE,
        "cognition_planning_layer",
        EXECUTION_SUBSTRATE_ROLE,
        ORCHESTRATION_LAYER_ROLE,
    }
)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class GuardSeverity(str, Enum):
    """Severity level of a single guard finding."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class GuardFinding:
    """A single finding produced by one architecture guard check.

    Attributes
    ----------
    code:
        Short machine-readable invariant identifier, e.g.
        ``"SOURCE_REGISTRY_SHELL_OWNED"`` or ``"SUBSTRATE_SELF_PROMOTION"``.
    severity:
        :class:`GuardSeverity` of this finding.
    message:
        Human-readable description that is actionable for future contributors.
    detail:
        Optional mapping of supplementary context (e.g. found vs. expected
        values), making failures self-explanatory.
    """

    code: str
    severity: GuardSeverity
    message: str
    detail: Optional[Dict[str, Any]] = field(default=None)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        out: Dict[str, Any] = {
            "code": self.code,
            "severity": self.severity.value if isinstance(self.severity, GuardSeverity) else self.severity,
            "message": self.message,
        }
        if self.detail:
            out["detail"] = self.detail
        return out


@dataclass
class GuardReport:
    """Aggregated result of one or more architecture guard checks.

    Attributes
    ----------
    passed:
        ``True`` when no ERROR-severity findings are present.
    findings:
        All findings produced during the run.
    error_count, warning_count, info_count:
        Convenience counters.
    checks_run:
        Names of the invariant checks that were executed.
    """

    passed: bool
    findings: List[GuardFinding] = field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    checks_run: List[str] = field(default_factory=list)

    def format_failures(self) -> str:
        """Return a human-readable summary of all ERROR-severity findings.

        Returns an empty string when there are no failures, making it safe to
        use in ``assert report.passed, report.format_failures()``.
        """
        lines = []
        for f in self.findings:
            sev = f.severity.value if isinstance(f.severity, GuardSeverity) else f.severity
            if sev == "error":
                detail_str = f" | detail={f.detail}" if f.detail else ""
                lines.append(f"[{f.code}] {f.message}{detail_str}")
        return "\n".join(lines) if lines else ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "passed": self.passed,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "checks_run": list(self.checks_run),
            "findings": [f.to_dict() for f in self.findings],
        }

    def to_json(self, **kwargs: Any) -> str:
        """Serialise to a JSON string."""
        return json.dumps(self.to_dict(), **kwargs)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_role(layer_data: Any) -> Optional[str]:
    """Extract an authority_role string from a layer snapshot dict."""
    if not isinstance(layer_data, dict):
        return None
    return layer_data.get("authority_role") or layer_data.get("arch_layer_id")


def _get_flag(layer_data: Any, key: str, default: bool = False) -> bool:
    """Safely read a boolean flag from a layer snapshot dict."""
    if not isinstance(layer_data, dict):
        return default
    val = layer_data.get(key, default)
    return bool(val)


# ---------------------------------------------------------------------------
# Guard accumulator
# ---------------------------------------------------------------------------


class _GuardAccumulator:
    """Internal stateful accumulator used during a guard run."""

    def __init__(self) -> None:
        self._findings: List[GuardFinding] = []
        self._checks: List[str] = []

    def record(self, check_name: str) -> None:
        if check_name not in self._checks:
            self._checks.append(check_name)

    def _add(
        self,
        code: str,
        severity: GuardSeverity,
        message: str,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._findings.append(
            GuardFinding(code=code, severity=severity, message=message, detail=detail)
        )

    def info(self, code: str, message: str, detail: Optional[Dict[str, Any]] = None) -> None:
        self._add(code, GuardSeverity.INFO, message, detail)

    def warn(self, code: str, message: str, detail: Optional[Dict[str, Any]] = None) -> None:
        self._add(code, GuardSeverity.WARNING, message, detail)

    def error(self, code: str, message: str, detail: Optional[Dict[str, Any]] = None) -> None:
        self._add(code, GuardSeverity.ERROR, message, detail)

    def build_report(self) -> GuardReport:
        errors = sum(
            1 for f in self._findings
            if (f.severity.value if isinstance(f.severity, GuardSeverity) else f.severity) == "error"
        )
        warnings = sum(
            1 for f in self._findings
            if (f.severity.value if isinstance(f.severity, GuardSeverity) else f.severity) == "warning"
        )
        infos = sum(
            1 for f in self._findings
            if (f.severity.value if isinstance(f.severity, GuardSeverity) else f.severity) == "info"
        )
        return GuardReport(
            passed=errors == 0,
            findings=list(self._findings),
            error_count=errors,
            warning_count=warnings,
            info_count=infos,
            checks_run=list(self._checks),
        )


# ---------------------------------------------------------------------------
# CanonicalTruthOwnershipGuard
# ---------------------------------------------------------------------------


class CanonicalTruthOwnershipGuard:
    """Fine-grained static assertions for canonical truth ownership.

    Each method accepts a plain-dict snapshot and returns a
    :class:`GuardReport` containing any findings.  All methods are
    intentionally stateless so that they compose freely.

    Snapshot keys expected by each method are documented per method.
    """

    # ------------------------------------------------------------------
    # Invariant 1: Source registry is shell-owned
    # ------------------------------------------------------------------

    @staticmethod
    def assert_source_registry_is_shell_owned(
        snapshot: Dict[str, Any],
    ) -> GuardReport:
        """Assert that the source registry is owned exclusively by the shell.

        Checks:
        - ``runtime_shell.owns_source_registry`` is truthy, **or** the
          ``runtime_shell`` layer is present (indicating it is the correct
          owner).
        - ``subject_core.owns_source_registry`` is falsy (OpenClawd must
          not own a source registry).
        - No other layer in *snapshot* exposes ``owns_source_registry=True``.

        Parameters
        ----------
        snapshot:
            Dict with optional keys ``"runtime_shell"`` and ``"subject_core"``
            (and any other layer keys) whose values are plain dicts.
        """
        acc = _GuardAccumulator()
        acc.record("SOURCE_REGISTRY_SHELL_OWNED")

        runtime_shell = snapshot.get("runtime_shell") or {}
        subject_core = snapshot.get("subject_core") or {}

        # Runtime shell must own (or at least not disclaim) the registry
        shell_owns = _get_flag(runtime_shell, "owns_source_registry", default=True)
        if not shell_owns:
            acc.error(
                "SOURCE_REGISTRY_SHELL_OWNED",
                "runtime_shell.owns_source_registry is False — the shell must "
                "be the sole owner of the perception source registry.",
                detail={"layer": "runtime_shell", "owns_source_registry": False},
            )
        else:
            acc.info(
                "SOURCE_REGISTRY_SHELL_OWNED",
                "runtime_shell correctly owns the perception source registry.",
            )

        # OpenClawd / subject_core must NOT own the registry
        core_owns = _get_flag(subject_core, "owns_source_registry", default=False)
        if core_owns:
            acc.error(
                "SUBJECT_CORE_MUST_NOT_OWN_SOURCE_REGISTRY",
                "subject_core.owns_source_registry is True — OpenClawd must "
                "receive the source registry snapshot from the shell, not own "
                "one independently. This would create a duplicate truth path.",
                detail={"layer": "subject_core", "owns_source_registry": True},
            )
        else:
            acc.info(
                "SUBJECT_CORE_MUST_NOT_OWN_SOURCE_REGISTRY",
                "subject_core correctly does not own the perception source registry.",
            )

        # No other layer should claim registry ownership
        skip = {"runtime_shell", "subject_core"}
        for layer_name, layer_data in snapshot.items():
            if layer_name in skip or not isinstance(layer_data, dict):
                continue
            if _get_flag(layer_data, "owns_source_registry", default=False):
                acc.error(
                    "DUPLICATE_SOURCE_REGISTRY_OWNER",
                    f"Layer '{layer_name}' claims owns_source_registry=True — "
                    "only the runtime shell may own the source registry.",
                    detail={"layer": layer_name},
                )

        return acc.build_report()

    # ------------------------------------------------------------------
    # Invariant 2: OpenClawd is the final model/execution authority
    # ------------------------------------------------------------------

    @staticmethod
    def assert_openclawd_is_final_authority(
        snapshot: Dict[str, Any],
    ) -> GuardReport:
        """Assert that OpenClawd / subject_core is the sole final authority.

        Checks:
        - ``subject_core.authority_role == "subject_decision_authority"``
        - ``subject_core.is_final_model_authority`` is truthy (when present)
        - No downstream layer (substrate, orchestration, projection) claims
          ``authority_role == "subject_decision_authority"``

        Parameters
        ----------
        snapshot:
            Dict with at least a ``"subject_core"`` key.
        """
        acc = _GuardAccumulator()
        acc.record("OPENCLAWD_IS_FINAL_AUTHORITY")

        subject_core = snapshot.get("subject_core") or {}

        # Subject core must carry the canonical authority role
        role = _get_role(subject_core)
        if role != SUBJECT_CORE_AUTHORITY_ROLE:
            acc.error(
                "SUBJECT_CORE_WRONG_AUTHORITY_ROLE",
                f"subject_core.authority_role must be '{SUBJECT_CORE_AUTHORITY_ROLE}' "
                f"but found '{role}'. OpenClawd must declare itself the subject "
                "decision authority.",
                detail={"found": role, "expected": SUBJECT_CORE_AUTHORITY_ROLE},
            )
        else:
            acc.info(
                "SUBJECT_CORE_AUTHORITY_ROLE_VALID",
                "subject_core correctly carries subject_decision_authority.",
            )

        # is_final_model_authority must not be explicitly False
        if isinstance(subject_core, dict) and "is_final_model_authority" in subject_core:
            if not subject_core["is_final_model_authority"]:
                acc.error(
                    "SUBJECT_CORE_MUST_BE_FINAL_MODEL_AUTHORITY",
                    "subject_core.is_final_model_authority is False — "
                    "OpenClawd must be the final model selection authority.",
                    detail={"layer": "subject_core"},
                )

        # No other layer may claim subject_decision_authority
        skip = {"subject_core"}
        for layer_name, layer_data in snapshot.items():
            if layer_name in skip or not isinstance(layer_data, dict):
                continue
            layer_role = _get_role(layer_data)
            if layer_role == SUBJECT_CORE_AUTHORITY_ROLE:
                acc.error(
                    "DUPLICATE_SUBJECT_DECISION_AUTHORITY",
                    f"Layer '{layer_name}' claims subject_decision_authority — "
                    "only OpenClawd (subject_core) may hold this role.",
                    detail={"layer": layer_name, "authority_role": layer_role},
                )

        return acc.build_report()

    # ------------------------------------------------------------------
    # Invariant 3: Canonical model supply is the capability truth layer
    # ------------------------------------------------------------------

    @staticmethod
    def assert_canonical_supply_is_capability_truth(
        snapshot: Dict[str, Any],
    ) -> GuardReport:
        """Assert that the canonical model supply state is the truth layer.

        Checks:
        - ``canonical_supply.is_canonical_supply_layer`` is truthy
        - No non-canonical layer (router, provider adapter, substrate) claims
          ``is_capability_truth=True``
        - ``routing_decision`` (when present) derives from the canonical
          supply and does not contain an independent capability registry

        Parameters
        ----------
        snapshot:
            Dict with optional keys ``"canonical_supply"``, ``"router"``,
            ``"provider_adapter"``, and ``"routing_decision"``.
        """
        acc = _GuardAccumulator()
        acc.record("CANONICAL_SUPPLY_IS_CAPABILITY_TRUTH")

        canonical_supply = snapshot.get("canonical_supply") or {}

        # Canonical supply layer must identify itself
        if isinstance(canonical_supply, dict) and canonical_supply:
            if not _get_flag(canonical_supply, "is_canonical_supply_layer", default=True):
                acc.error(
                    "CANONICAL_SUPPLY_LAYER_NOT_DECLARED",
                    "canonical_supply.is_canonical_supply_layer is False — "
                    "the canonical model supply state must declare itself as "
                    "the capability truth layer.",
                    detail={"layer": "canonical_supply"},
                )
            else:
                acc.info(
                    "CANONICAL_SUPPLY_LAYER_DECLARED",
                    "canonical_supply correctly identifies as the capability truth layer.",
                )

        # Non-canonical layers must not claim capability truth
        non_canonical_layers = {"router", "provider_adapter", "execution_substrate"}
        for layer_name in non_canonical_layers:
            layer_data = snapshot.get(layer_name) or {}
            if not isinstance(layer_data, dict):
                continue
            if _get_flag(layer_data, "is_capability_truth", default=False):
                acc.error(
                    "NON_CANONICAL_CAPABILITY_TRUTH",
                    f"Layer '{layer_name}' claims is_capability_truth=True — "
                    "only the canonical model supply layer may be the capability "
                    "truth source. This would introduce a duplicate truth path.",
                    detail={"layer": layer_name},
                )

        # Routing decisions must derive from canonical supply
        routing_decision = snapshot.get("routing_decision") or {}
        if isinstance(routing_decision, dict) and routing_decision:
            if "independent_capability_registry" in routing_decision:
                if routing_decision["independent_capability_registry"]:
                    acc.error(
                        "ROUTER_INDEPENDENT_CAPABILITY_REGISTRY",
                        "routing_decision.independent_capability_registry is True — "
                        "routing decisions must derive capability facts from the "
                        "canonical supply layer, not build their own registry.",
                        detail={"layer": "routing_decision"},
                    )
            sourced = routing_decision.get("sourced_from_canonical_supply")
            if sourced is False:
                acc.error(
                    "ROUTING_DECISION_NOT_FROM_CANONICAL_SUPPLY",
                    "routing_decision.sourced_from_canonical_supply is False — "
                    "routing decisions must be derived from canonical model supply state.",
                    detail={"layer": "routing_decision"},
                )

        return acc.build_report()

    # ------------------------------------------------------------------
    # Invariant 4: Projection does not reconstruct truth
    # ------------------------------------------------------------------

    @staticmethod
    def assert_projection_does_not_reconstruct_truth(
        snapshot: Dict[str, Any],
    ) -> GuardReport:
        """Assert that the projection / desktop-status layer is a consumer.

        Checks:
        - ``projection.is_truth_reconstruction_layer`` is falsy
        - ``projection.sourced_from_canonical_plan`` is truthy (when present)
        - Projection does not expose ``owns_source_registry=True``
        - Projection does not expose ``is_final_model_authority=True``

        Parameters
        ----------
        snapshot:
            Dict with an optional ``"projection"`` key.
        """
        acc = _GuardAccumulator()
        acc.record("PROJECTION_DOES_NOT_RECONSTRUCT_TRUTH")

        projection = snapshot.get("projection") or {}
        if not isinstance(projection, dict) or not projection:
            acc.info(
                "PROJECTION_NOT_PRESENT",
                "No projection layer found in snapshot; skipping projection truth check.",
            )
            return acc.build_report()

        # Must not be a truth reconstruction layer
        if _get_flag(projection, "is_truth_reconstruction_layer", default=False):
            acc.error(
                "PROJECTION_RECONSTRUCTS_TRUTH",
                "projection.is_truth_reconstruction_layer is True — the "
                "projection/desktop-status layer must consume canonical "
                "control-plan artifacts and must not reconstruct truth "
                "independently.",
                detail={"layer": "projection"},
            )
        else:
            acc.info(
                "PROJECTION_IS_CONSUMER",
                "projection correctly does not reconstruct truth.",
            )

        # Must source from canonical plan when flag is present
        if "sourced_from_canonical_plan" in projection:
            if not projection["sourced_from_canonical_plan"]:
                acc.error(
                    "PROJECTION_NOT_SOURCED_FROM_CANONICAL_PLAN",
                    "projection.sourced_from_canonical_plan is False — "
                    "desktop status projection must derive all displayed state "
                    "from the canonical unified control plan.",
                    detail={"layer": "projection"},
                )

        # Projection must not own source registry
        if _get_flag(projection, "owns_source_registry", default=False):
            acc.error(
                "PROJECTION_OWNS_SOURCE_REGISTRY",
                "projection.owns_source_registry is True — projection is a "
                "downstream consumer and must not own the source registry.",
                detail={"layer": "projection"},
            )

        # Projection must not claim model authority
        if _get_flag(projection, "is_final_model_authority", default=False):
            acc.error(
                "PROJECTION_CLAIMS_MODEL_AUTHORITY",
                "projection.is_final_model_authority is True — the projection "
                "layer must not make or claim final model selection decisions.",
                detail={"layer": "projection"},
            )

        return acc.build_report()


# ---------------------------------------------------------------------------
# BoundaryInvariantGuard
# ---------------------------------------------------------------------------


class BoundaryInvariantGuard:
    """Fine-grained static assertions for layer boundary invariants.

    These guards prevent substrate and orchestration components from
    self-promoting to higher authority levels, and ensure there are no
    duplicate truth paths between layers.
    """

    # ------------------------------------------------------------------
    # Invariant 5: Substrate does not self-promote
    # ------------------------------------------------------------------

    @staticmethod
    def assert_substrate_does_not_self_promote(
        snapshot: Dict[str, Any],
    ) -> GuardReport:
        """Assert that the execution substrate stays within its authority.

        Checks:
        - ``execution_substrate.authority_role == "execution_substrate"``
        - ``execution_substrate`` does not claim any elevated role
        - ``execution_substrate.is_final_model_authority`` is falsy

        Parameters
        ----------
        snapshot:
            Dict with optional ``"execution_substrate"`` key.
        """
        acc = _GuardAccumulator()
        acc.record("SUBSTRATE_DOES_NOT_SELF_PROMOTE")

        substrate = snapshot.get("execution_substrate") or {}
        if not isinstance(substrate, dict) or not substrate:
            acc.info(
                "SUBSTRATE_NOT_PRESENT",
                "No execution_substrate layer found in snapshot; skipping.",
            )
            return acc.build_report()

        role = _get_role(substrate)
        if role in _ELEVATED_ROLES:
            acc.error(
                "SUBSTRATE_SELF_PROMOTION",
                f"execution_substrate claims elevated role '{role}' — the "
                "execution substrate must not claim runtime_shell_authority or "
                "subject_decision_authority. It must remain "
                f"'{EXECUTION_SUBSTRATE_ROLE}'.",
                detail={"found": role, "allowed": EXECUTION_SUBSTRATE_ROLE},
            )
        elif role and role != EXECUTION_SUBSTRATE_ROLE:
            acc.warn(
                "SUBSTRATE_UNEXPECTED_ROLE",
                f"execution_substrate has unexpected authority_role '{role}'; "
                f"expected '{EXECUTION_SUBSTRATE_ROLE}'.",
                detail={"found": role, "expected": EXECUTION_SUBSTRATE_ROLE},
            )
        else:
            acc.info(
                "SUBSTRATE_ROLE_VALID",
                f"execution_substrate correctly holds role '{EXECUTION_SUBSTRATE_ROLE}'.",
            )

        # Substrate must not claim model authority
        if _get_flag(substrate, "is_final_model_authority", default=False):
            acc.error(
                "SUBSTRATE_CLAIMS_MODEL_AUTHORITY",
                "execution_substrate.is_final_model_authority is True — the "
                "substrate layer must never make final model selection decisions.",
                detail={"layer": "execution_substrate"},
            )

        # Substrate must not claim policy authority
        if _get_flag(substrate, "is_policy_authority", default=False):
            acc.error(
                "SUBSTRATE_CLAIMS_POLICY_AUTHORITY",
                "execution_substrate.is_policy_authority is True — the "
                "substrate layer must not self-promote to policy authority.",
                detail={"layer": "execution_substrate"},
            )

        return acc.build_report()

    # ------------------------------------------------------------------
    # Invariant 6: Orchestration is distinct from substrate and subject authority
    # ------------------------------------------------------------------

    @staticmethod
    def assert_orchestration_distinct_from_substrate_and_authority(
        snapshot: Dict[str, Any],
    ) -> GuardReport:
        """Assert that orchestration does not blur into substrate or authority.

        Checks:
        - ``orchestration_layer.authority_role == "orchestration_layer"``
        - Orchestration does not claim ``"execution_substrate"`` role
        - Orchestration does not claim ``"subject_decision_authority"`` role
        - ``execution_substrate.authority_role != "orchestration_layer"``

        Parameters
        ----------
        snapshot:
            Dict with optional ``"orchestration_layer"`` and
            ``"execution_substrate"`` keys.
        """
        acc = _GuardAccumulator()
        acc.record("ORCHESTRATION_DISTINCT_FROM_SUBSTRATE_AND_AUTHORITY")

        orchestration = snapshot.get("orchestration_layer") or {}
        substrate = snapshot.get("execution_substrate") or {}

        # Orchestration must carry its own role
        if isinstance(orchestration, dict) and orchestration:
            orch_role = _get_role(orchestration)
            if orch_role == EXECUTION_SUBSTRATE_ROLE:
                acc.error(
                    "ORCHESTRATION_CONFLATED_WITH_SUBSTRATE",
                    "orchestration_layer claims 'execution_substrate' role — "
                    "orchestration (SwarmCoordinator) must remain distinct from "
                    "the execution substrate (CommandRouter).",
                    detail={"found": orch_role},
                )
            elif orch_role == SUBJECT_CORE_AUTHORITY_ROLE:
                acc.error(
                    "ORCHESTRATION_CLAIMS_SUBJECT_AUTHORITY",
                    "orchestration_layer claims 'subject_decision_authority' — "
                    "orchestration must not self-promote to subject core authority.",
                    detail={"found": orch_role},
                )
            elif orch_role and orch_role != ORCHESTRATION_LAYER_ROLE:
                acc.warn(
                    "ORCHESTRATION_UNEXPECTED_ROLE",
                    f"orchestration_layer has unexpected role '{orch_role}'; "
                    f"expected '{ORCHESTRATION_LAYER_ROLE}'.",
                    detail={"found": orch_role},
                )
            else:
                acc.info(
                    "ORCHESTRATION_ROLE_VALID",
                    "orchestration_layer correctly holds 'orchestration_layer' role.",
                )

        # Substrate must not claim orchestration role
        if isinstance(substrate, dict) and substrate:
            sub_role = _get_role(substrate)
            if sub_role == ORCHESTRATION_LAYER_ROLE:
                acc.error(
                    "SUBSTRATE_CONFLATED_WITH_ORCHESTRATION",
                    "execution_substrate claims 'orchestration_layer' role — "
                    "the substrate must not absorb orchestration responsibility.",
                    detail={"found": sub_role},
                )

        return acc.build_report()

    # ------------------------------------------------------------------
    # Invariant 7: Routers / provider adapters do not bypass policy authority
    # ------------------------------------------------------------------

    @staticmethod
    def assert_router_not_final_authority(
        snapshot: Dict[str, Any],
    ) -> GuardReport:
        """Assert that routers and provider adapters are not final authorities.

        Checks:
        - ``router.is_final_model_authority`` is falsy
        - ``provider_adapter.is_final_model_authority`` is falsy
        - ``router.authority_role`` is not an elevated role
        - ``provider_adapter.authority_role`` is not an elevated role

        Parameters
        ----------
        snapshot:
            Dict with optional ``"router"`` and ``"provider_adapter"`` keys.
        """
        acc = _GuardAccumulator()
        acc.record("ROUTER_NOT_FINAL_AUTHORITY")

        downstream_layers = {
            "router": snapshot.get("router") or {},
            "provider_adapter": snapshot.get("provider_adapter") or {},
        }

        for layer_name, layer_data in downstream_layers.items():
            if not isinstance(layer_data, dict) or not layer_data:
                continue

            # Must not claim final model authority
            if _get_flag(layer_data, "is_final_model_authority", default=False):
                acc.error(
                    "ROUTER_CLAIMS_FINAL_MODEL_AUTHORITY",
                    f"'{layer_name}' claims is_final_model_authority=True — "
                    "routers and provider adapters must not be final authorities. "
                    "Final model selection authority belongs to OpenClawd (subject_core).",
                    detail={"layer": layer_name},
                )
            else:
                acc.info(
                    "ROUTER_NOT_AUTHORITY",
                    f"'{layer_name}' correctly does not claim final model authority.",
                )

            # Must not claim elevated authority role
            layer_role = _get_role(layer_data)
            if layer_role in _ELEVATED_ROLES:
                acc.error(
                    "ROUTER_ELEVATED_AUTHORITY_ROLE",
                    f"'{layer_name}' claims elevated authority role '{layer_role}' — "
                    "routers and provider adapters must not claim shell or subject "
                    "decision authority.",
                    detail={"layer": layer_name, "found": layer_role},
                )

        return acc.build_report()

    # ------------------------------------------------------------------
    # Invariant 7b: No duplicate truth paths
    # ------------------------------------------------------------------

    @staticmethod
    def assert_no_duplicate_truth_paths(
        snapshot: Dict[str, Any],
    ) -> GuardReport:
        """Assert that there are no duplicate source registries or capability truths.

        Checks:
        - At most one layer claims ``owns_source_registry=True``
        - At most one layer claims ``is_capability_truth=True``

        Parameters
        ----------
        snapshot:
            Full architecture snapshot dict.
        """
        acc = _GuardAccumulator()
        acc.record("NO_DUPLICATE_TRUTH_PATHS")

        registry_owners: List[str] = []
        capability_truth_owners: List[str] = []

        for layer_name, layer_data in snapshot.items():
            if not isinstance(layer_data, dict):
                continue
            if _get_flag(layer_data, "owns_source_registry", default=False):
                registry_owners.append(layer_name)
            if _get_flag(layer_data, "is_capability_truth", default=False):
                capability_truth_owners.append(layer_name)

        if len(registry_owners) > 1:
            acc.error(
                "DUPLICATE_SOURCE_REGISTRY",
                f"Multiple layers claim owns_source_registry=True: "
                f"{registry_owners}. Only the runtime shell must own the "
                "source registry; all others must consume a snapshot.",
                detail={"owners": registry_owners},
            )
        elif registry_owners:
            acc.info(
                "SINGLE_SOURCE_REGISTRY",
                f"Exactly one layer owns the source registry: {registry_owners[0]}.",
            )

        if len(capability_truth_owners) > 1:
            acc.error(
                "DUPLICATE_CAPABILITY_TRUTH",
                f"Multiple layers claim is_capability_truth=True: "
                f"{capability_truth_owners}. Only the canonical model supply "
                "layer may be the capability truth source.",
                detail={"owners": capability_truth_owners},
            )
        elif capability_truth_owners:
            acc.info(
                "SINGLE_CAPABILITY_TRUTH",
                f"Exactly one layer owns capability truth: {capability_truth_owners[0]}.",
            )

        return acc.build_report()


# ---------------------------------------------------------------------------
# High-level entry points
# ---------------------------------------------------------------------------


def _merge_reports(*reports: GuardReport, extra_checks: Optional[List[str]] = None) -> GuardReport:
    """Merge multiple GuardReport instances into one."""
    all_findings: List[GuardFinding] = []
    all_checks: List[str] = []
    for r in reports:
        all_findings.extend(r.findings)
        for c in r.checks_run:
            if c not in all_checks:
                all_checks.append(c)
    if extra_checks:
        for c in extra_checks:
            if c not in all_checks:
                all_checks.append(c)

    errors = sum(
        1 for f in all_findings
        if (f.severity.value if isinstance(f.severity, GuardSeverity) else f.severity) == "error"
    )
    warnings = sum(
        1 for f in all_findings
        if (f.severity.value if isinstance(f.severity, GuardSeverity) else f.severity) == "warning"
    )
    infos = sum(
        1 for f in all_findings
        if (f.severity.value if isinstance(f.severity, GuardSeverity) else f.severity) == "info"
    )
    return GuardReport(
        passed=errors == 0,
        findings=all_findings,
        error_count=errors,
        warning_count=warnings,
        info_count=infos,
        checks_run=all_checks,
    )


def run_canonical_truth_ownership_checks(
    snapshot: Optional[Dict[str, Any]] = None,
) -> GuardReport:
    """Run all canonical truth ownership invariants (invariants 1–4).

    Invariants checked:
    1. Source registry is shell-owned
    2. OpenClawd is the final model/execution authority
    3. Canonical model supply is the capability truth layer
    4. Projection does not reconstruct truth

    Parameters
    ----------
    snapshot:
        Architecture snapshot dict.  May be ``None`` or empty — the function
        never raises; it may return a report with only INFO findings when
        there is nothing to check.

    Returns
    -------
    GuardReport
        ``passed=True`` when no ERROR findings are present.
    """
    if not snapshot or not isinstance(snapshot, dict):
        acc = _GuardAccumulator()
        acc.record("CANONICAL_TRUTH_OWNERSHIP")
        acc.info(
            "EMPTY_SNAPSHOT",
            "Snapshot is empty or None; canonical truth ownership checks skipped.",
        )
        return acc.build_report()

    try:
        r1 = CanonicalTruthOwnershipGuard.assert_source_registry_is_shell_owned(snapshot)
        r2 = CanonicalTruthOwnershipGuard.assert_openclawd_is_final_authority(snapshot)
        r3 = CanonicalTruthOwnershipGuard.assert_canonical_supply_is_capability_truth(snapshot)
        r4 = CanonicalTruthOwnershipGuard.assert_projection_does_not_reconstruct_truth(snapshot)
        return _merge_reports(r1, r2, r3, r4)
    except Exception as exc:  # pragma: no cover
        logger.exception("run_canonical_truth_ownership_checks failed unexpectedly: %s", exc)
        acc = _GuardAccumulator()
        acc.record("CANONICAL_TRUTH_OWNERSHIP")
        acc.error(
            "GUARD_INTERNAL_ERROR",
            f"Unexpected error during canonical truth ownership checks: {exc}",
        )
        return acc.build_report()


def run_boundary_invariant_checks(
    snapshot: Optional[Dict[str, Any]] = None,
) -> GuardReport:
    """Run all boundary invariant guards (invariants 5–7).

    Invariants checked:
    5. Execution substrate does not self-promote
    6. Orchestration remains distinct from substrate and subject authority
    7. Routers / provider adapters do not bypass policy/control authority
    7b. No duplicate truth paths

    Parameters
    ----------
    snapshot:
        Architecture snapshot dict.  May be ``None`` or empty.

    Returns
    -------
    GuardReport
        ``passed=True`` when no ERROR findings are present.
    """
    if not snapshot or not isinstance(snapshot, dict):
        acc = _GuardAccumulator()
        acc.record("BOUNDARY_INVARIANTS")
        acc.info(
            "EMPTY_SNAPSHOT",
            "Snapshot is empty or None; boundary invariant checks skipped.",
        )
        return acc.build_report()

    try:
        r5 = BoundaryInvariantGuard.assert_substrate_does_not_self_promote(snapshot)
        r6 = BoundaryInvariantGuard.assert_orchestration_distinct_from_substrate_and_authority(snapshot)
        r7 = BoundaryInvariantGuard.assert_router_not_final_authority(snapshot)
        r7b = BoundaryInvariantGuard.assert_no_duplicate_truth_paths(snapshot)
        return _merge_reports(r5, r6, r7, r7b)
    except Exception as exc:  # pragma: no cover
        logger.exception("run_boundary_invariant_checks failed unexpectedly: %s", exc)
        acc = _GuardAccumulator()
        acc.record("BOUNDARY_INVARIANTS")
        acc.error(
            "GUARD_INTERNAL_ERROR",
            f"Unexpected error during boundary invariant checks: {exc}",
        )
        return acc.build_report()


def run_all_architecture_guards(
    snapshot: Optional[Dict[str, Any]] = None,
) -> GuardReport:
    """Run all architecture guards and return a single merged :class:`GuardReport`.

    This is the recommended entry point for test suites and CI invariant
    checks.  It combines:

    - Canonical truth ownership checks (invariants 1–4)
    - Boundary invariant checks (invariants 5–7b)

    The returned report is fully JSON-serialisable via :meth:`GuardReport.to_dict`.

    Parameters
    ----------
    snapshot:
        Architecture snapshot dict.  May be ``None`` or empty.

    Returns
    -------
    GuardReport
        Use ``assert report.passed, report.format_failures()`` to make guard
        failures clearly actionable for future contributors.

    Example
    -------
    ::

        snapshot = build_architecture_snapshot_for_flow(response_dict)
        report = run_all_architecture_guards(snapshot)
        assert report.passed, report.format_failures()
    """
    ownership = run_canonical_truth_ownership_checks(snapshot)
    boundary = run_boundary_invariant_checks(snapshot)
    return _merge_reports(ownership, boundary)


# ---------------------------------------------------------------------------
# Snapshot builder helper
# ---------------------------------------------------------------------------


def build_architecture_snapshot_from_response(
    response: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a minimal architecture snapshot from a unified response dict.

    Extracts layer metadata embedded by PR-9/PR-10 (``arch_layer_id``,
    ``authority_role``, ``authority_metadata``) from a representative
    response and returns a snapshot dict suitable for passing to
    :func:`run_all_architecture_guards`.

    This helper is intentionally conservative — it never raises and only
    includes keys that are explicitly present in the input.

    Parameters
    ----------
    response:
        A response or metadata dict that may contain ``arch_layer_id`` and
        ``authority_role`` fields at the top level or inside ``"metadata"``.

    Returns
    -------
    dict
        Flat snapshot dict keyed by layer name.
    """
    if not isinstance(response, dict):
        return {}

    snapshot: Dict[str, Any] = {}

    def _extract_layer(data: Dict[str, Any]) -> Optional[str]:
        return data.get("arch_layer_id") or data.get("layer_id")

    # Top-level layer stamp
    layer_id = _extract_layer(response)
    if layer_id:
        snapshot[layer_id] = dict(response)

    # Nested metadata layer stamps
    for key in ("metadata", "authority_metadata"):
        meta = response.get(key)
        if isinstance(meta, dict):
            meta_layer = _extract_layer(meta)
            if meta_layer and meta_layer not in snapshot:
                snapshot[meta_layer] = dict(meta)

    return snapshot
