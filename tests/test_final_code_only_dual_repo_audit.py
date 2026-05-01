"""
tests/test_final_code_only_dual_repo_audit.py
===============================================

Tests for the final code-only dual-repo audit module.

These tests validate that every check in
``core.final_code_only_dual_repo_audit`` passes against the current codebase.

Methodology note
----------------
These tests do NOT assert on fixed verdict constants — they verify that the
underlying implementation code referenced by each check actually exists and
satisfies the structural requirements.  If implementation code changes (e.g.
a handler is removed or a sentinel is renamed), the relevant test will fail
explicitly, which is the correct behavior for a code-grounded audit.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Import the audit module — this must not raise.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def audit_module():
    from core import final_code_only_dual_repo_audit as m
    return m


# ---------------------------------------------------------------------------
# Methodology guard
# ---------------------------------------------------------------------------


def test_audit_methodology_is_declared(audit_module):
    """The module must declare an explicit methodology statement."""
    assert isinstance(audit_module.AUDIT_METHODOLOGY, str)
    assert len(audit_module.AUDIT_METHODOLOGY) > 50
    assert "code" in audit_module.AUDIT_METHODOLOGY.lower()


def test_deployment_conditions_are_explicit(audit_module):
    """Deployment conditions must be a non-empty list of strings."""
    assert isinstance(audit_module.DEPLOYMENT_CONDITIONS, list)
    assert len(audit_module.DEPLOYMENT_CONDITIONS) >= 1
    for cond in audit_module.DEPLOYMENT_CONDITIONS:
        assert isinstance(cond, str), f"Condition must be a string: {cond!r}"


def test_system_verdict_is_declared(audit_module):
    """SYSTEM_VERDICT must be a non-empty string."""
    assert isinstance(audit_module.SYSTEM_VERDICT, str)
    assert len(audit_module.SYSTEM_VERDICT) > 5


def test_system_verdict_explanation_is_declared(audit_module):
    """SYSTEM_VERDICT_EXPLANATION must explain the verdict."""
    assert isinstance(audit_module.SYSTEM_VERDICT_EXPLANATION, str)
    assert len(audit_module.SYSTEM_VERDICT_EXPLANATION) > 50


# ---------------------------------------------------------------------------
# Individual check tests — each verifies that the check passes.
# ---------------------------------------------------------------------------


def test_check_canonical_ws_ingress(audit_module):
    result = audit_module.check_canonical_ws_ingress()
    assert result.passed, (
        f"check_canonical_ws_ingress FAILED: {result.failure_detail}"
    )


def test_check_message_type_coverage(audit_module):
    result = audit_module.check_message_type_coverage()
    assert result.passed, (
        f"check_message_type_coverage FAILED: {result.failure_detail}"
    )


def test_check_handler_registration_completeness(audit_module):
    result = audit_module.check_handler_registration_completeness()
    assert result.passed, (
        f"check_handler_registration_completeness FAILED: {result.failure_detail}"
    )


def test_check_reconciliation_signal_handler_wired(audit_module):
    result = audit_module.check_reconciliation_signal_handler_wired()
    assert result.passed, (
        f"check_reconciliation_signal_handler_wired FAILED: {result.failure_detail}"
    )


def test_check_handoff_v2_result_handler_wired(audit_module):
    result = audit_module.check_handoff_v2_result_handler_wired()
    assert result.passed, (
        f"check_handoff_v2_result_handler_wired FAILED: {result.failure_detail}"
    )


def test_check_pending_delivery_buffer_implemented(audit_module):
    result = audit_module.check_pending_delivery_buffer_implemented()
    assert result.passed, (
        f"check_pending_delivery_buffer_implemented FAILED: {result.failure_detail}"
    )


def test_check_reconnect_canonical_path_sentinel(audit_module):
    result = audit_module.check_reconnect_canonical_path_sentinel()
    assert result.passed, (
        f"check_reconnect_canonical_path_sentinel FAILED: {result.failure_detail}"
    )


def test_check_attached_session_registry_reconnect(audit_module):
    result = audit_module.check_attached_session_registry_reconnect()
    assert result.passed, (
        f"check_attached_session_registry_reconnect FAILED: {result.failure_detail}"
    )


def test_check_governance_gate_enforcement_sentinel(audit_module):
    result = audit_module.check_governance_gate_enforcement_sentinel()
    assert result.passed, (
        f"check_governance_gate_enforcement_sentinel FAILED: {result.failure_detail}"
    )


def test_check_cross_repo_consistency_gates_implemented(audit_module):
    result = audit_module.check_cross_repo_consistency_gates_implemented()
    assert result.passed, (
        f"check_cross_repo_consistency_gates_implemented FAILED: {result.failure_detail}"
    )


def test_check_dispatch_blocked_on_registration_gap(audit_module):
    result = audit_module.check_dispatch_blocked_on_registration_gap()
    assert result.passed, (
        f"check_dispatch_blocked_on_registration_gap FAILED: {result.failure_detail}"
    )


def test_check_aip_compat_normalizer(audit_module):
    result = audit_module.check_aip_compat_normalizer()
    assert result.passed, (
        f"check_aip_compat_normalizer FAILED: {result.failure_detail}"
    )


def test_check_lifecycle_coordinator_exists(audit_module):
    result = audit_module.check_lifecycle_coordinator_exists()
    assert result.passed, (
        f"check_lifecycle_coordinator_exists FAILED: {result.failure_detail}"
    )


# ---------------------------------------------------------------------------
# Snapshot integration test
# ---------------------------------------------------------------------------


def test_build_audit_snapshot_structure(audit_module):
    """build_audit_snapshot() must return a dict with required keys."""
    snapshot = audit_module.build_audit_snapshot()
    assert isinstance(snapshot, dict)
    required_keys = {
        "methodology", "verdict", "deployment_conditions",
        "checks", "passed_count", "failed_count", "all_checks_passed",
    }
    assert required_keys.issubset(set(snapshot.keys()))


def test_build_audit_snapshot_all_checks_pass(audit_module):
    """All checks in the snapshot must pass."""
    snapshot = audit_module.build_audit_snapshot()
    failed = [c for c in snapshot["checks"] if not c["passed"]]
    assert snapshot["all_checks_passed"], (
        f"{snapshot['failed_count']} check(s) failed:\n"
        + "\n".join(
            f"  [{c['check_name']}] {c['failure_detail']}"
            for c in failed
        )
    )


def test_build_audit_snapshot_verdict_is_string(audit_module):
    """The verdict in the snapshot must be a non-empty string."""
    snapshot = audit_module.build_audit_snapshot()
    assert isinstance(snapshot["verdict"], str)
    assert len(snapshot["verdict"]) > 5


def test_build_audit_snapshot_deployment_conditions_present(audit_module):
    """The snapshot must include at least one deployment condition."""
    snapshot = audit_module.build_audit_snapshot()
    assert isinstance(snapshot["deployment_conditions"], list)
    assert len(snapshot["deployment_conditions"]) >= 1


def test_build_audit_snapshot_checks_have_evidence(audit_module):
    """Every check result must include a non-empty evidence string."""
    snapshot = audit_module.build_audit_snapshot()
    for check in snapshot["checks"]:
        assert isinstance(check["evidence"], str), (
            f"Check {check['check_name']!r} has no evidence string"
        )
        assert len(check["evidence"]) > 5, (
            f"Check {check['check_name']!r} has too-short evidence: {check['evidence']!r}"
        )
