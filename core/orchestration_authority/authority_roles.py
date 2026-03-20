#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.orchestration_authority.authority_roles
============================================

PR-9 (V3) — Orchestration Authority Consolidation

Defines the **formal authority-role taxonomy** for orchestration layers in the
Galaxy runtime.  The taxonomy answers:
  *"Which module/path owns which level of orchestration authority?"*

Roles
-----
+-----------------------------+------------------------------------------------+
| Role                        | Canonical module                               |
+=============================+================================================+
| AUTHORITATIVE_ENTRYPOINT    | core.desktop_presence_runtime                  |
|                             | (DesktopPresenceRuntime)                       |
+-----------------------------+------------------------------------------------+
| EXECUTION_RUNTIME_DELEGATE  | core.constellation_runtime                     |
|                             | (ConstellationRuntime)                         |
+-----------------------------+------------------------------------------------+
| DAG_EXECUTION_ENGINE        | core.task_graph                                |
|                             | (TaskGraph)                                    |
+-----------------------------+------------------------------------------------+
| ORCHESTRATION_COORDINATOR   | core.e2e_orchestrator                          |
|                             | (process_user_input, compile_and_run_dag)      |
+-----------------------------+------------------------------------------------+
| LEGACY_COMPATIBILITY        | galaxy_gateway.orchestrator.task_orchestrator  |
|                             | nodes.Node_110_SmartOrchestrator.*             |
|                             | nodes.Node_81_Orchestrator.*                   |
+-----------------------------+------------------------------------------------+
| DEPRECATED                  | nodes.Node_50_Transformer.task_orchestrator    |
+-----------------------------+------------------------------------------------+
| UNKNOWN                     | Unclassified modules/paths                     |
+-----------------------------+------------------------------------------------+

These definitions are **additive** — they do not modify any existing module.

Usage::

    from core.orchestration_authority import AuthorityRole, ROLE_CATALOG

    info = ROLE_CATALOG[AuthorityRole.AUTHORITATIVE_ENTRYPOINT]
    print(info["canonical_module"])   # "core.desktop_presence_runtime"
    print(info["description"])        # human-readable description
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict

__all__ = [
    "AuthorityRole",
    "ROLE_CATALOG",
    "ROLE_DESCRIPTIONS",
    "role_label",
    "is_authoritative",
    "is_legacy_or_deprecated",
]


# ---------------------------------------------------------------------------
# Authority role enum
# ---------------------------------------------------------------------------


class AuthorityRole(str, Enum):
    """Taxonomy of orchestration authority levels in the Galaxy runtime.

    The string values are stable identifiers safe for serialisation, logging,
    and API responses.  They intentionally mirror the vocabulary used in
    ``docs/ORCHESTRATION_AUTHORITY_CONSOLIDATION.md``.
    """

    #: The single control-plane entry chain.  All high-level requests pass
    #: through this role before reaching any execution layer.
    AUTHORITATIVE_ENTRYPOINT = "authoritative_entrypoint"

    #: Active runtime delegate that handles LLM planning → DAG → execution.
    EXECUTION_RUNTIME_DELEGATE = "execution_runtime_delegate"

    #: Lower-level, reusable DAG execution engine.  Not a top-level entrypoint.
    DAG_EXECUTION_ENGINE = "dag_execution_engine"

    #: Convenience coordinator that wires together the control-plane and
    #: runtime-delegate layers.  Not itself an authority; defers upward.
    ORCHESTRATION_COORDINATOR = "orchestration_coordinator"

    #: Older module still in active use for backwards compatibility; should
    #: not be called as the primary entry point for new code.
    LEGACY_COMPATIBILITY = "legacy_compatibility"

    #: Module explicitly replaced by a successor; kept for migration only.
    DEPRECATED = "deprecated"

    #: Could not be classified against known authority paths.
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Machine-readable catalog
# ---------------------------------------------------------------------------

#: Maps each :class:`AuthorityRole` to a rich metadata dict.
ROLE_CATALOG: Dict[AuthorityRole, Dict[str, Any]] = {
    AuthorityRole.AUTHORITATIVE_ENTRYPOINT: {
        "role": AuthorityRole.AUTHORITATIVE_ENTRYPOINT.value,
        "label": "Authoritative Control-Plane Entrypoint",
        "canonical_module": "core.desktop_presence_runtime",
        "canonical_class": "DesktopPresenceRuntime",
        "canonical_factory": "core.desktop_presence_runtime.get_desktop_presence_runtime",
        "description": (
            "Single control-plane runtime and authoritative high-level request "
            "entrypoint.  All chat / OpenClawd / E2E requests are routed through "
            "DesktopPresenceRuntime, which owns the canonical tri-state progression "
            "(silent → liminal → manifest → silent) and emits a runtime_session_id "
            "propagated throughout the entire request lifecycle."
        ),
        "downstream_delegates": [
            AuthorityRole.EXECUTION_RUNTIME_DELEGATE.value,
            AuthorityRole.ORCHESTRATION_COORDINATOR.value,
        ],
        "pr_introduced": "PR-1",
        "active": True,
    },
    AuthorityRole.EXECUTION_RUNTIME_DELEGATE: {
        "role": AuthorityRole.EXECUTION_RUNTIME_DELEGATE.value,
        "label": "Execution Runtime Delegate",
        "canonical_module": "core.constellation_runtime",
        "canonical_class": "ConstellationRuntime",
        "canonical_factory": "core.constellation_runtime.get_constellation_runtime",
        "description": (
            "Active runtime execution path that closes the planning → DAG → "
            "execution loop for TaskConstellation-based orchestration.  Receives "
            "delegated requests from DesktopPresenceRuntime.  Already includes "
            "LEGACY_ORCHESTRATOR_PATHS registry and warn_legacy_path() guardrail."
        ),
        "downstream_delegates": [
            AuthorityRole.DAG_EXECUTION_ENGINE.value,
        ],
        "pr_introduced": "PR-1",
        "active": True,
    },
    AuthorityRole.DAG_EXECUTION_ENGINE: {
        "role": AuthorityRole.DAG_EXECUTION_ENGINE.value,
        "label": "DAG Execution Engine",
        "canonical_module": "core.task_graph",
        "canonical_class": "TaskGraph",
        "canonical_factory": None,
        "description": (
            "Lower-level, reusable dependency-graph execution engine.  Supports "
            "parallel execution, per-node retry, partial rollback, and "
            "trace_id / runtime_session_id propagation.  Explicitly NOT a "
            "replacement for core.orchestrator_engine.DAGScheduler, which "
            "operates on LLM-driven SubTask decompositions.  Consumed by both "
            "ConstellationRuntime and E2EOrchestrator for multi-device tasks."
        ),
        "downstream_delegates": [],
        "pr_introduced": "PR-5",
        "active": True,
    },
    AuthorityRole.ORCHESTRATION_COORDINATOR: {
        "role": AuthorityRole.ORCHESTRATION_COORDINATOR.value,
        "label": "Orchestration Coordinator (convenience wrapper)",
        "canonical_module": "core.e2e_orchestrator",
        "canonical_class": None,
        "canonical_factory": "core.e2e_orchestrator.process_user_input",
        "description": (
            "Convenience coordinator that exposes process_user_input() and "
            "compile_and_run_dag() as stable top-level APIs.  Internally "
            "delegates to DesktopPresenceRuntime (control-plane) → "
            "ConstellationRuntime (runtime delegate).  All multi-device "
            "tasks are forced through TaskGraph via run_multi_device_via_task_graph()."
        ),
        "downstream_delegates": [
            AuthorityRole.AUTHORITATIVE_ENTRYPOINT.value,
            AuthorityRole.DAG_EXECUTION_ENGINE.value,
        ],
        "pr_introduced": "PR-2",
        "active": True,
    },
    AuthorityRole.LEGACY_COMPATIBILITY: {
        "role": AuthorityRole.LEGACY_COMPATIBILITY.value,
        "label": "Legacy Compatibility Path",
        "canonical_module": None,
        "canonical_class": None,
        "canonical_factory": None,
        "description": (
            "Older orchestration modules that remain active for compatibility "
            "with existing integrations but should NOT be used as primary entry "
            "points for new code.  Migration guidance: route new code through "
            "core.e2e_orchestrator.process_user_input() or directly through "
            "core.desktop_presence_runtime.get_desktop_presence_runtime()."
        ),
        "downstream_delegates": [],
        "pr_introduced": None,
        "active": True,
    },
    AuthorityRole.DEPRECATED: {
        "role": AuthorityRole.DEPRECATED.value,
        "label": "Deprecated Path",
        "canonical_module": None,
        "canonical_class": None,
        "canonical_factory": None,
        "description": (
            "Modules explicitly superseded by newer layers.  May be kept for "
            "reference or thin-wrapper compatibility but must not be called "
            "as active orchestration paths.  No further investment planned."
        ),
        "downstream_delegates": [],
        "pr_introduced": None,
        "active": False,
    },
    AuthorityRole.UNKNOWN: {
        "role": AuthorityRole.UNKNOWN.value,
        "label": "Unknown / Unclassified",
        "canonical_module": None,
        "canonical_class": None,
        "canonical_factory": None,
        "description": (
            "Module or path that could not be matched against any known "
            "authority entry.  Classification should be refined over time."
        ),
        "downstream_delegates": [],
        "pr_introduced": None,
        "active": None,
    },
}

#: Flat string-keyed descriptions (role value → description string).
#: Useful for logging/docs generation without full metadata traversal.
ROLE_DESCRIPTIONS: Dict[str, str] = {
    role.value: info["description"]
    for role, info in ROLE_CATALOG.items()
}


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def role_label(role: AuthorityRole) -> str:
    """Return the human-readable label for *role*."""
    return ROLE_CATALOG[role]["label"]


def is_authoritative(role: AuthorityRole) -> bool:
    """Return True if *role* represents a currently active authority path."""
    return ROLE_CATALOG[role].get("active") is True


def is_legacy_or_deprecated(role: AuthorityRole) -> bool:
    """Return True if *role* is :attr:`~AuthorityRole.LEGACY_COMPATIBILITY`
    or :attr:`~AuthorityRole.DEPRECATED`."""
    return role in (AuthorityRole.LEGACY_COMPATIBILITY, AuthorityRole.DEPRECATED)
