"""
core/node_audit.py — Canonical Node-System Audit Module
=========================================================

PR-6: Node-system audit and canonical inventory establishment.
PR-2 (upgrade): Promoted to the repository-wide canonical governance engine.

Exposes the full audit engine so that tests and other core modules can import
and use node-audit logic without invoking the CLI entry-point.

Public API
----------
NodeTier              — quality-tier constants
RecommendedAction     — disposition constants
NodeAuditEntry        — per-node audit record dataclass (expanded in PR-2)
NodeAuditReport       — aggregate audit report dataclass (expanded in PR-2)
run_audit(project_root) → NodeAuditReport

Check category constants (PR-2)
--------------------------------
CHECK_SOURCE_COMPLETENESS  — "source_completeness"
CHECK_SYNTAX_SAFETY        — "syntax_safety"
CHECK_PACKAGING            — "packaging"
CHECK_REGISTRY_GOVERNANCE  — "registry_governance"
CHECK_RUNTIME_CONTRACT     — "runtime_contract"
CHECK_HYGIENE              — "hygiene"

Check result constants (PR-2)
------------------------------
CHECK_PASS / CHECK_WARN / CHECK_FAIL / CHECK_UNKNOWN
"""

from scripts.node_audit import (  # re-export for importability
    NodeTier,
    RecommendedAction,
    NodeAuditEntry,
    NodeAuditReport,
    run_audit,
    # PR-2: check category constants
    CHECK_SOURCE_COMPLETENESS,
    CHECK_SYNTAX_SAFETY,
    CHECK_PACKAGING,
    CHECK_REGISTRY_GOVERNANCE,
    CHECK_RUNTIME_CONTRACT,
    CHECK_HYGIENE,
    # PR-2: check result constants
    CHECK_PASS,
    CHECK_WARN,
    CHECK_FAIL,
    CHECK_UNKNOWN,
)

__all__ = [
    "NodeTier",
    "RecommendedAction",
    "NodeAuditEntry",
    "NodeAuditReport",
    "run_audit",
    # PR-2
    "CHECK_SOURCE_COMPLETENESS",
    "CHECK_SYNTAX_SAFETY",
    "CHECK_PACKAGING",
    "CHECK_REGISTRY_GOVERNANCE",
    "CHECK_RUNTIME_CONTRACT",
    "CHECK_HYGIENE",
    "CHECK_PASS",
    "CHECK_WARN",
    "CHECK_FAIL",
    "CHECK_UNKNOWN",
]
