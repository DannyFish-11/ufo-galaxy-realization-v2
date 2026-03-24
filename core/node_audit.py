"""
core/node_audit.py — Canonical Node-System Audit Module
=========================================================

PR-6: Node-system audit and canonical inventory establishment.

Exposes the audit engine so that tests and other core modules can import and
use node-audit logic without invoking the CLI entry-point.

Public API
----------
NodeTier          — quality-tier constants
RecommendedAction — disposition constants
NodeAuditEntry    — per-node audit record dataclass
NodeAuditReport   — aggregate audit report dataclass
run_audit(project_root) → NodeAuditReport
"""

from scripts.node_audit import (  # re-export for importability
    NodeTier,
    RecommendedAction,
    NodeAuditEntry,
    NodeAuditReport,
    run_audit,
)

__all__ = [
    "NodeTier",
    "RecommendedAction",
    "NodeAuditEntry",
    "NodeAuditReport",
    "run_audit",
]
