"""tests/test_deepest_dual_repo_cognition_audit.py
===================================================

Tests for core/deepest_dual_repo_cognition_audit.py

These tests verify that the machine-checkable cognition audit checks
operate correctly.  They mirror the structure of the companion tests for
``core/final_code_only_dual_repo_audit.py`` (PR-35).

Test scope:
  1. All checks that should pass DO pass (architecture, OpenClawd, chains,
     multimodal, transport, config)
  2. The android_model_checksums_populated check correctly flags the gap
  3. build_cognition_audit_snapshot() returns the expected structure
  4. SYSTEM_VERDICT has the correct format
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helper: run the full snapshot once
# ---------------------------------------------------------------------------

_snapshot = None


def _get_snapshot():
    global _snapshot
    if _snapshot is None:
        from core.deepest_dual_repo_cognition_audit import build_cognition_audit_snapshot
        _snapshot = build_cognition_audit_snapshot()
    return _snapshot


def _get_check(name: str):
    snapshot = _get_snapshot()
    for c in snapshot["checks"]:
        if c["check_name"] == name:
            return c
    pytest.fail(f"Check '{name}' not found in snapshot")


# ---------------------------------------------------------------------------
# 1. Architecture checks
# ---------------------------------------------------------------------------


class TestArchitectureChecks:
    def test_tristate_ownership_passes(self):
        c = _get_check("desktop_presence_runtime_tristate_ownership")
        assert c["passed"], c["failure_detail"]

    def test_runtime_session_id_propagation_passes(self):
        c = _get_check("runtime_session_id_propagation")
        assert c["passed"], c["failure_detail"]


# ---------------------------------------------------------------------------
# 2. OpenClawd checks
# ---------------------------------------------------------------------------


class TestOpenClawdChecks:
    def test_subject_core_existence_passes(self):
        c = _get_check("openclawd_subject_core_existence")
        assert c["passed"], c["failure_detail"]

    def test_multimodal_sentinel_passes(self):
        c = _get_check("openclawd_critical_path_multimodal_sentinel")
        assert c["passed"], c["failure_detail"]

    def test_spine_observability_sentinel_passes(self):
        c = _get_check("openclawd_spine_observability_sentinel")
        assert c["passed"], c["failure_detail"]


# ---------------------------------------------------------------------------
# 3. Execution chain checks
# ---------------------------------------------------------------------------


class TestExecutionChainChecks:
    def test_local_chain_steps_passes(self):
        c = _get_check("local_execution_chain_steps")
        assert c["passed"], c["failure_detail"]

    def test_cross_device_chain_passes(self):
        c = _get_check("cross_device_chain_step_authority_model")
        assert c["passed"], c["failure_detail"]

    def test_handoff_envelope_v2_wire_format_passes(self):
        c = _get_check("handoff_envelope_v2_android_wire_format")
        assert c["passed"], c["failure_detail"]


# ---------------------------------------------------------------------------
# 4. Multimodal checks
# ---------------------------------------------------------------------------


class TestMultimodalChecks:
    def test_ingress_bus_existence_passes(self):
        c = _get_check("multimodal_ingress_bus_existence")
        assert c["passed"], c["failure_detail"]

    def test_android_vlm_service_existence_passes(self):
        c = _get_check("android_vlm_service_existence")
        assert c["passed"], c["failure_detail"]

    def test_android_model_checksums_flags_gap(self):
        """The SHA-256 checksum gap must be flagged, not silently ignored."""
        c = _get_check("android_model_checksums_populated")
        assert not c["passed"], (
            "Expected android_model_checksums_populated to flag the empty-SHA-256 gap, "
            "but it passed. Fill in real checksums and update this test."
        )
        assert c["failure_detail"] is not None
        assert "sha256" in c["failure_detail"].lower() or "empty" in c["failure_detail"].lower()


# ---------------------------------------------------------------------------
# 5. Transport / recovery checks
# ---------------------------------------------------------------------------


class TestTransportRecoveryChecks:
    def test_pending_delivery_buffer_passes(self):
        c = _get_check("pending_delivery_buffer_guarantees")
        assert c["passed"], c["failure_detail"]

    def test_nats_bus_graceful_degradation_passes(self):
        c = _get_check("nats_bus_graceful_degradation")
        assert c["passed"], c["failure_detail"]


# ---------------------------------------------------------------------------
# 7. Config / operator checks
# ---------------------------------------------------------------------------


class TestConfigOperatorChecks:
    def test_config_service_network_url_surface_passes(self):
        c = _get_check("config_service_network_url_surface")
        assert c["passed"], c["failure_detail"]

    def test_url_config_surface_renders_passes(self):
        c = _get_check("url_config_surface_renders")
        assert c["passed"], c["failure_detail"]

    def test_config_control_surface_passes(self):
        c = _get_check("config_control_surface_apply_network_url")
        assert c["passed"], c["failure_detail"]


# ---------------------------------------------------------------------------
# Snapshot structure tests
# ---------------------------------------------------------------------------


class TestSnapshotStructure:
    def test_snapshot_has_required_keys(self):
        snapshot = _get_snapshot()
        for key in ("checks", "passed", "failed", "verdict", "gap_summary",
                    "hard_failures", "methodology"):
            assert key in snapshot, f"Key '{key}' missing from snapshot"

    def test_no_hard_failures(self):
        snapshot = _get_snapshot()
        assert snapshot["hard_failures"] == [], (
            f"Unexpected hard failures: {snapshot['hard_failures']}"
        )

    def test_verdict_is_passed(self):
        snapshot = _get_snapshot()
        assert snapshot["verdict"] == "COGNITION_AUDIT_PASSED", (
            f"Expected COGNITION_AUDIT_PASSED, got {snapshot['verdict']}"
        )

    def test_total_check_count(self):
        snapshot = _get_snapshot()
        assert len(snapshot["checks"]) >= 16, (
            f"Expected >=16 checks, got {len(snapshot['checks'])}"
        )

    def test_methodology_string(self):
        snapshot = _get_snapshot()
        assert "DEEPEST_DUAL_REPO_COGNITION_AUDIT" in snapshot["methodology"]


class TestSystemVerdict:
    def test_system_verdict_format(self):
        from core.deepest_dual_repo_cognition_audit import SYSTEM_VERDICT

        assert "CENTER_GOVERNED" in SYSTEM_VERDICT
        assert "DISTRIBUTED" in SYSTEM_VERDICT
        assert "OPERATOR_PLANE_CLOSURE_UNFINISHED" in SYSTEM_VERDICT
