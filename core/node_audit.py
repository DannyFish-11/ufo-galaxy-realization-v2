"""
core/node_audit.py — Canonical Node-System Audit Module
=========================================================

PR-6: Node-system audit and canonical inventory establishment.
PR-2 (upgrade): Promoted to the repository-wide canonical governance engine.
PR-5 (upgrade): Unified packaging coverage into the canonical audit.

Exposes the full audit engine so that tests and other core modules can import
and use node-audit logic without invoking the CLI entry-point.

Public API
----------
NodeTier              — quality-tier constants
RecommendedAction     — disposition constants
NodePackagingStatus   — per-node structured packaging record (PR-5)
NodeAuditEntry        — per-node audit record dataclass (expanded in PR-2/PR-5)
NodeAuditReport       — aggregate audit report dataclass (expanded in PR-2/PR-5)
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

Packaging policy-class constants (PR-5)
----------------------------------------
PACKAGING_POLICY_ACTIVE       — "active"
PACKAGING_POLICY_OPTIONAL     — "optional"
PACKAGING_POLICY_SKIP         — "skip"
PACKAGING_POLICY_UNREGISTERED — "unregistered"
"""

# re-export for importability; PR-2: check category/result constants;
# PR-5: packaging policy-class constants
from scripts.node_audit import (
    CHECK_FAIL,
    CHECK_HYGIENE,
    CHECK_PACKAGING,
    CHECK_PASS,
    CHECK_REGISTRY_GOVERNANCE,
    CHECK_RUNTIME_CONTRACT,
    CHECK_SOURCE_COMPLETENESS,
    CHECK_SYNTAX_SAFETY,
    CHECK_UNKNOWN,
    CHECK_WARN,
    PACKAGING_POLICY_ACTIVE,
    PACKAGING_POLICY_OPTIONAL,
    PACKAGING_POLICY_SKIP,
    PACKAGING_POLICY_UNREGISTERED,
    NodeAuditEntry,
    NodeAuditReport,
    NodePackagingStatus,
    NodeTier,
    RecommendedAction,
    run_audit,
)

__all__ = [
    "NodeTier",
    "RecommendedAction",
    "NodePackagingStatus",
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
    # PR-5
    "PACKAGING_POLICY_ACTIVE",
    "PACKAGING_POLICY_OPTIONAL",
    "PACKAGING_POLICY_SKIP",
    "PACKAGING_POLICY_UNREGISTERED",
]
