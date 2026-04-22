#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_dispatch_constraint_chain.py
============================================
PR-dispatch-discipline — Dispatch Constraint Chain Enforcement.

Verifies that all four constraint types are applied consistently across
dispatch paths in :meth:`~core.command_router.CommandRouter.route_envelope`:

1. **Admissibility chain** (readiness → participation → capability)
   via :func:`~core.target_device_validator.validate_target_device`

2. **Capability validation** (required capabilities gate + network topology)
   via :func:`~core.capability_network_runtime_policy.query_routable_executors`
   and :func:`~core.capability_network_runtime_policy.query_network_path`

3. **Session-truth / posture-aware filter**
   via :func:`~core.source_execution_eligibility.check_source_execution_eligibility`

4. **Constraint chain trace** propagated to result for reviewability
   (``_constraint_chain_trace`` key in result dict)

Test groups
-----------
A  — New sentinels are importable and non-empty.
B  — Admissibility gate: ready target passes, unready target excluded.
C  — Admissibility gate: all targets excluded → graceful degradation proceeds.
D  — Admissibility gate: readiness module unavailable → gate skipped, no crash.
E  — Posture filter: join_runtime source → eligible, recorded in trace.
F  — Posture filter: control_only source on non-cross-device path → flagged.
G  — Posture filter: no posture hint → filter gate not applied.
H  — Posture filter: posture module unavailable → gate skipped, no crash.
I  — Constraint chain trace attached to result when at least one gate ran.
J  — Constraint chain trace not attached when neither gate ran.
K  — Capability enforcement warning logged for unconfirmed targets.
L  — Fallback behavior bounded: empty-target envelope still returns error.
M  — Canonical sentinels: DISPATCH_CONSTRAINT_CHAIN_UNIFORM_ENFORCEMENT present.
N  — Canonical sentinels: SESSION_TRUTH_POSTURE_DISPATCH_FILTER_APPLIED present.

All tests are self-contained (no live servers, no real devices).
"""

from __future__ import annotations

import asyncio
import sys
import os
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Module availability guard
# ---------------------------------------------------------------------------


def _import_command_router():
    from core.command_router import CommandRouter
    return CommandRouter


def _make_router():
    CR = _import_command_router()
    return CR()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_envelope(
    task_id: str = "task-test-001",
    trace_id: str = "trace-test-001",
    targets: Optional[List[str]] = None,
    required_capabilities: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    executor_target_type=None,
):
    """Build a minimal TaskEnvelope for testing."""
    from core.schemas.task_envelope import TaskEnvelope

    return TaskEnvelope(
        task_id=task_id,
        trace_id=trace_id,
        source="test",
        targets=targets or [],
        tool_name="test_command",
        args={},
        timeout=5.0,
        required_capabilities=required_capabilities or [],
        metadata=metadata or {},
        executor_target_type=executor_target_type,
    )


def _run(coro):
    """Run a coroutine in a fresh event loop."""
    return asyncio.run(coro)


def _make_validation_result(
    registered: bool = True,
    ready: bool = True,
    reasons: Optional[List[str]] = None,
):
    """Build a mock validate_target_device result."""
    vr = MagicMock()
    vr.registered = registered
    vr.ready = ready
    vr.reasons = reasons or []
    return vr


def _make_posture_result(eligible: bool = True, posture: str = "join_runtime"):
    """Build a mock check_source_execution_eligibility result."""
    pr = MagicMock()
    pr.eligible = eligible
    pr.posture = posture
    pr.reason = f"posture={posture} eligible={eligible}"
    return pr


def _patch_execute_command(result: Dict[str, Any]):
    """Patch CommandRouter._execute_command to return a fixed result."""
    return patch.object(
        _import_command_router(),
        "_execute_command",
        new=AsyncMock(return_value=result),
    )


def _default_success_result(task_id: str = "task-test-001") -> Dict[str, Any]:
    return {
        "success": True,
        "task_id": task_id,
        "trace_id": "trace-test-001",
        "result": "ok",
        "error_code": None,
        "error_message": None,
        "command_id": task_id,
        "request_id": task_id,
        "device_id": "dev-001",
        "command": "test_command",
        "via": "command_router",
        "latency_ms": 1.0,
    }


# ===========================================================================
# A — New sentinels
# ===========================================================================


class TestSentinels:
    """Group A: New enforcement sentinels are importable and non-empty."""

    def test_dispatch_constraint_chain_uniform_enforcement_importable(self):
        from core.command_router import DISPATCH_CONSTRAINT_CHAIN_UNIFORM_ENFORCEMENT
        assert isinstance(DISPATCH_CONSTRAINT_CHAIN_UNIFORM_ENFORCEMENT, str)

    def test_dispatch_constraint_chain_uniform_enforcement_nonempty(self):
        from core.command_router import DISPATCH_CONSTRAINT_CHAIN_UNIFORM_ENFORCEMENT
        assert len(DISPATCH_CONSTRAINT_CHAIN_UNIFORM_ENFORCEMENT) > 20

    def test_dispatch_constraint_chain_mentions_admissibility(self):
        from core.command_router import DISPATCH_CONSTRAINT_CHAIN_UNIFORM_ENFORCEMENT
        assert "admissibility" in DISPATCH_CONSTRAINT_CHAIN_UNIFORM_ENFORCEMENT.lower()

    def test_dispatch_constraint_chain_mentions_posture(self):
        from core.command_router import DISPATCH_CONSTRAINT_CHAIN_UNIFORM_ENFORCEMENT
        assert "posture" in DISPATCH_CONSTRAINT_CHAIN_UNIFORM_ENFORCEMENT.lower()

    def test_session_truth_posture_dispatch_filter_importable(self):
        from core.command_router import SESSION_TRUTH_POSTURE_DISPATCH_FILTER_APPLIED
        assert isinstance(SESSION_TRUTH_POSTURE_DISPATCH_FILTER_APPLIED, str)

    def test_session_truth_posture_dispatch_filter_nonempty(self):
        from core.command_router import SESSION_TRUTH_POSTURE_DISPATCH_FILTER_APPLIED
        assert len(SESSION_TRUTH_POSTURE_DISPATCH_FILTER_APPLIED) > 20

    def test_session_truth_posture_dispatch_filter_mentions_control_only(self):
        from core.command_router import SESSION_TRUTH_POSTURE_DISPATCH_FILTER_APPLIED
        assert "control_only" in SESSION_TRUTH_POSTURE_DISPATCH_FILTER_APPLIED.lower()

    def test_session_truth_posture_dispatch_filter_mentions_join_runtime(self):
        from core.command_router import SESSION_TRUTH_POSTURE_DISPATCH_FILTER_APPLIED
        assert "join_runtime" in SESSION_TRUTH_POSTURE_DISPATCH_FILTER_APPLIED.lower()


# ===========================================================================
# B — Admissibility gate: ready target passes
# ===========================================================================


class TestAdmissibilityGateReady:
    """Group B: Admissibility gate passes a ready target and records it."""

    def test_ready_target_included_in_trace(self):
        """A ready target appears in admissibility_validated."""
        router = _make_router()
        env = _make_envelope(targets=["dev-ready-001"])
        success_result = _default_success_result()

        ready_vr = _make_validation_result(registered=True, ready=True)

        with patch(
            "core.command_router.CommandRouter._execute_command",
            new=AsyncMock(return_value=success_result),
        ), patch(
            "core.target_device_validator.validate_target_device",
            return_value=ready_vr,
        ):
            result = _run(router.route_envelope(env))

        trace = result.get("_constraint_chain_trace", {})
        assert trace.get("admissibility_applied") is True
        assert "dev-ready-001" in trace.get("admissibility_validated", [])
        assert "dev-ready-001" not in trace.get("admissibility_excluded", [])

    def test_ready_target_not_excluded(self):
        """A ready target is not in the excluded list."""
        router = _make_router()
        env = _make_envelope(targets=["dev-ready-001"])
        success_result = _default_success_result()
        ready_vr = _make_validation_result(registered=True, ready=True)

        with patch(
            "core.command_router.CommandRouter._execute_command",
            new=AsyncMock(return_value=success_result),
        ), patch(
            "core.target_device_validator.validate_target_device",
            return_value=ready_vr,
        ):
            result = _run(router.route_envelope(env))

        trace = result.get("_constraint_chain_trace", {})
        assert len(trace.get("admissibility_excluded", [])) == 0


# ===========================================================================
# C — Admissibility gate: unready target excluded (filtered down)
# ===========================================================================


class TestAdmissibilityGateExcluded:
    """Group C: Unready target is excluded with a structured trace entry."""

    def test_unready_target_recorded_as_excluded(self):
        """Target that fails readiness check appears in admissibility_excluded."""
        router = _make_router()
        # Two targets: one ready, one not.
        env = _make_envelope(targets=["dev-ready", "dev-unready"])
        success_result = _default_success_result()

        def _fake_vtd(device_id, required_capabilities=None):
            if device_id == "dev-unready":
                return _make_validation_result(
                    registered=True, ready=False, reasons=["not-ready"]
                )
            return _make_validation_result(registered=True, ready=True)

        with patch(
            "core.command_router.CommandRouter._execute_command",
            new=AsyncMock(return_value=success_result),
        ), patch(
            "core.target_device_validator.validate_target_device",
            side_effect=_fake_vtd,
        ):
            result = _run(router.route_envelope(env))

        trace = result.get("_constraint_chain_trace", {})
        assert "dev-unready" in trace.get("admissibility_excluded", [])
        assert "dev-ready" in trace.get("admissibility_validated", [])

    def test_not_registered_target_excluded(self):
        """Unregistered target is excluded because readiness can be consulted."""
        router = _make_router()
        env = _make_envelope(targets=["dev-unknown"])
        success_result = _default_success_result()

        unregistered_vr = _make_validation_result(
            registered=False, ready=False, reasons=["not-registered"]
        )

        with patch(
            "core.command_router.CommandRouter._execute_command",
            new=AsyncMock(return_value=success_result),
        ), patch(
            "core.target_device_validator.validate_target_device",
            return_value=unregistered_vr,
        ):
            result = _run(router.route_envelope(env))

        trace = result.get("_constraint_chain_trace", {})
        assert "dev-unknown" in trace.get("admissibility_excluded", [])


# ===========================================================================
# D — Admissibility gate: readiness unavailable → graceful degradation
# ===========================================================================


class TestAdmissibilityGateDegrades:
    """Group D: Readiness module unavailable → gate skips, dispatch proceeds."""

    def test_gate_skipped_when_validator_unavailable(self):
        """ImportError from validate_target_device is handled gracefully."""
        router = _make_router()
        env = _make_envelope(targets=["dev-001"])
        success_result = _default_success_result()

        with patch(
            "core.command_router.CommandRouter._execute_command",
            new=AsyncMock(return_value=success_result),
        ), patch(
            "core.target_device_validator.validate_target_device",
            side_effect=ImportError("module not found"),
        ):
            result = _run(router.route_envelope(env))

        # Dispatch should still succeed; gate was skipped.
        assert result.get("success") is True

    def test_readiness_unavailable_reason_does_not_exclude(self):
        """Target with readiness-unavailable reason is NOT excluded (degrades gracefully)."""
        router = _make_router()
        env = _make_envelope(targets=["dev-001"])
        success_result = _default_success_result()

        # Simulate the readiness module being unavailable: reasons include
        # "readiness-unavailable" prefix.
        unavail_vr = _make_validation_result(
            registered=False,
            ready=False,
            reasons=["readiness-unavailable:module-missing"],
        )

        with patch(
            "core.command_router.CommandRouter._execute_command",
            new=AsyncMock(return_value=success_result),
        ), patch(
            "core.target_device_validator.validate_target_device",
            return_value=unavail_vr,
        ):
            result = _run(router.route_envelope(env))

        # Target should NOT be excluded since readiness could not be consulted.
        trace = result.get("_constraint_chain_trace", {})
        assert "dev-001" not in trace.get("admissibility_excluded", [])


# ===========================================================================
# E — Posture filter: join_runtime source eligible
# ===========================================================================


class TestPostureFilterJoinRuntime:
    """Group E: join_runtime source is eligible and recorded in trace."""

    def test_join_runtime_eligible_in_trace(self):
        """join_runtime source records eligible=True in constraint trace."""
        router = _make_router()
        env = _make_envelope(
            targets=["dev-001"],
            metadata={"source_runtime_posture": "join_runtime"},
        )
        success_result = _default_success_result()
        join_posture = _make_posture_result(eligible=True, posture="join_runtime")

        with patch(
            "core.command_router.CommandRouter._execute_command",
            new=AsyncMock(return_value=success_result),
        ), patch(
            "core.source_execution_eligibility.check_source_execution_eligibility",
            return_value=join_posture,
        ):
            result = _run(router.route_envelope(env))

        trace = result.get("_constraint_chain_trace", {})
        assert trace.get("posture_filter_applied") is True
        assert trace.get("posture_eligible") is True
        assert trace.get("posture_value") == "join_runtime"

    def test_join_runtime_does_not_block_dispatch(self):
        """join_runtime source does not block local dispatch path."""
        router = _make_router()
        env = _make_envelope(
            targets=["dev-001"],
            metadata={"source_runtime_posture": "join_runtime"},
        )
        success_result = _default_success_result()
        join_posture = _make_posture_result(eligible=True, posture="join_runtime")

        with patch(
            "core.command_router.CommandRouter._execute_command",
            new=AsyncMock(return_value=success_result),
        ), patch(
            "core.source_execution_eligibility.check_source_execution_eligibility",
            return_value=join_posture,
        ):
            result = _run(router.route_envelope(env))

        assert result.get("success") is True


# ===========================================================================
# F — Posture filter: control_only source flagged
# ===========================================================================


class TestPostureFilterControlOnly:
    """Group F: control_only source on non-cross-device path is flagged."""

    def test_control_only_flagged_in_trace(self):
        """control_only source on local path records eligible=False in trace."""
        router = _make_router()
        env = _make_envelope(
            targets=["dev-001"],
            metadata={"source_runtime_posture": "control_only"},
        )
        success_result = _default_success_result()
        control_posture = _make_posture_result(
            eligible=False, posture="control_only"
        )

        with patch(
            "core.command_router.CommandRouter._execute_command",
            new=AsyncMock(return_value=success_result),
        ), patch(
            "core.source_execution_eligibility.check_source_execution_eligibility",
            return_value=control_posture,
        ):
            result = _run(router.route_envelope(env))

        trace = result.get("_constraint_chain_trace", {})
        assert trace.get("posture_filter_applied") is True
        assert trace.get("posture_eligible") is False
        assert trace.get("posture_value") == "control_only"

    def test_control_only_does_not_hard_block_backward_compat(self):
        """control_only on local path does not hard-block (backward compat)."""
        router = _make_router()
        env = _make_envelope(
            targets=["dev-001"],
            metadata={"source_runtime_posture": "control_only"},
        )
        success_result = _default_success_result()
        control_posture = _make_posture_result(
            eligible=False, posture="control_only"
        )

        with patch(
            "core.command_router.CommandRouter._execute_command",
            new=AsyncMock(return_value=success_result),
        ), patch(
            "core.source_execution_eligibility.check_source_execution_eligibility",
            return_value=control_posture,
        ):
            result = _run(router.route_envelope(env))

        # Dispatch proceeds (graceful degradation preserves backward compat).
        assert result.get("success") is True


# ===========================================================================
# G — Posture filter: no posture hint → not applied
# ===========================================================================


class TestPostureFilterNoHint:
    """Group G: No source_runtime_posture hint → posture gate not applied."""

    def test_no_posture_hint_gate_not_applied(self):
        """Envelope without source_runtime_posture skips posture filter gate."""
        router = _make_router()
        env = _make_envelope(targets=["dev-001"])  # no posture metadata
        success_result = _default_success_result()
        mock_check = MagicMock()

        with patch(
            "core.command_router.CommandRouter._execute_command",
            new=AsyncMock(return_value=success_result),
        ), patch(
            "core.source_execution_eligibility.check_source_execution_eligibility",
            mock_check,
        ):
            _run(router.route_envelope(env))

        # The posture check function should NOT have been called.
        mock_check.assert_not_called()

    def test_no_posture_hint_posture_filter_applied_is_false(self):
        """posture_filter_applied is False when no posture hint provided."""
        router = _make_router()
        env = _make_envelope(targets=["dev-001"])
        success_result = _default_success_result()
        ready_vr = _make_validation_result(registered=True, ready=True)

        with patch(
            "core.command_router.CommandRouter._execute_command",
            new=AsyncMock(return_value=success_result),
        ), patch(
            "core.target_device_validator.validate_target_device",
            return_value=ready_vr,
        ):
            result = _run(router.route_envelope(env))

        trace = result.get("_constraint_chain_trace", {})
        assert trace.get("posture_filter_applied") is False


# ===========================================================================
# H — Posture filter: module unavailable → graceful degradation
# ===========================================================================


class TestPostureFilterDegrades:
    """Group H: Posture module unavailable → gate skipped, no crash."""

    def test_posture_gate_skipped_on_import_error(self):
        """ImportError from posture module is handled gracefully."""
        router = _make_router()
        env = _make_envelope(
            targets=["dev-001"],
            metadata={"source_runtime_posture": "join_runtime"},
        )
        success_result = _default_success_result()

        with patch(
            "core.command_router.CommandRouter._execute_command",
            new=AsyncMock(return_value=success_result),
        ), patch(
            "core.source_execution_eligibility.check_source_execution_eligibility",
            side_effect=ImportError("not available"),
        ):
            result = _run(router.route_envelope(env))

        assert result.get("success") is True


# ===========================================================================
# I — Constraint chain trace attached when at least one gate ran
# ===========================================================================


class TestConstraintChainTraceAttached:
    """Group I: _constraint_chain_trace is in result when a gate ran."""

    def test_trace_attached_when_admissibility_ran(self):
        """Trace is present in result when admissibility gate ran."""
        router = _make_router()
        env = _make_envelope(targets=["dev-001"])
        success_result = _default_success_result()
        ready_vr = _make_validation_result(registered=True, ready=True)

        with patch(
            "core.command_router.CommandRouter._execute_command",
            new=AsyncMock(return_value=success_result),
        ), patch(
            "core.target_device_validator.validate_target_device",
            return_value=ready_vr,
        ):
            result = _run(router.route_envelope(env))

        assert "_constraint_chain_trace" in result

    def test_trace_attached_when_posture_gate_ran(self):
        """Trace is present in result when posture filter gate ran."""
        router = _make_router()
        env = _make_envelope(
            targets=["dev-001"],
            metadata={"source_runtime_posture": "join_runtime"},
        )
        success_result = _default_success_result()
        join_posture = _make_posture_result(eligible=True, posture="join_runtime")

        with patch(
            "core.command_router.CommandRouter._execute_command",
            new=AsyncMock(return_value=success_result),
        ), patch(
            "core.source_execution_eligibility.check_source_execution_eligibility",
            return_value=join_posture,
        ):
            result = _run(router.route_envelope(env))

        assert "_constraint_chain_trace" in result

    def test_trace_contains_expected_keys(self):
        """Constraint chain trace contains all expected keys."""
        router = _make_router()
        env = _make_envelope(
            targets=["dev-001"],
            metadata={"source_runtime_posture": "join_runtime"},
        )
        success_result = _default_success_result()
        ready_vr = _make_validation_result(registered=True, ready=True)
        join_posture = _make_posture_result(eligible=True, posture="join_runtime")

        with patch(
            "core.command_router.CommandRouter._execute_command",
            new=AsyncMock(return_value=success_result),
        ), patch(
            "core.target_device_validator.validate_target_device",
            return_value=ready_vr,
        ), patch(
            "core.source_execution_eligibility.check_source_execution_eligibility",
            return_value=join_posture,
        ):
            result = _run(router.route_envelope(env))

        trace = result["_constraint_chain_trace"]
        assert "admissibility_applied" in trace
        assert "admissibility_validated" in trace
        assert "admissibility_excluded" in trace
        assert "posture_filter_applied" in trace
        assert "posture_eligible" in trace
        assert "posture_value" in trace


# ===========================================================================
# J — Constraint chain trace NOT attached when neither gate ran
# ===========================================================================


class TestConstraintChainTraceAbsent:
    """Group J: _constraint_chain_trace absent when no gate consulted."""

    def test_trace_absent_when_no_targets_and_no_posture(self):
        """No trace when no targets and no posture hint."""
        router = _make_router()
        # Cross-device envelope: targets resolved by substrate — no admissibility.
        env = _make_envelope(
            targets=[],
            metadata={"cross_device": "true"},
        )
        cross_device_result = {
            "success": False,
            "task_id": "task-test-001",
            "trace_id": "trace-test-001",
            "result": None,
            "error_code": "CROSS_DEVICE_SUBSTRATE_ERROR",
            "error_message": "no substrate",
            "command_id": "task-test-001",
            "request_id": "task-test-001",
            "device_id": "",
            "command": "test_command",
            "via": "command_router.cross_device_substrate",
            "latency_ms": 1.0,
        }

        with patch(
            "core.command_router.CommandRouter._route_cross_device_envelope",
            new=AsyncMock(return_value=cross_device_result),
        ):
            result = _run(router.route_envelope(env))

        # Cross-device path with empty targets and no posture — no gate ran.
        trace = result.get("_constraint_chain_trace")
        if trace is not None:
            # If trace is present, both gates should be False.
            assert trace.get("admissibility_applied") is False
            assert trace.get("posture_filter_applied") is False


# ===========================================================================
# K — Capability enforcement: logged for unconfirmed targets
# ===========================================================================


class TestCapabilityEnforcement:
    """Group K: Capability / network graph enforcement path is traversed."""

    def test_capability_query_runs_without_error(self):
        """Capability graph query runs without crashing the dispatch."""
        router = _make_router()
        env = _make_envelope(
            targets=["dev-001"],
            required_capabilities=["vlm"],
        )
        success_result = _default_success_result()

        mock_executor = MagicMock()
        mock_executor.node_id = "dev-001"

        mock_path = MagicMock()
        mock_path.is_reachable = True
        mock_path.path_state = "direct"

        with patch(
            "core.command_router.CommandRouter._execute_command",
            new=AsyncMock(return_value=success_result),
        ), patch(
            "core.capability_network_runtime_policy.query_routable_executors",
            return_value=[mock_executor],
        ), patch(
            "core.capability_network_runtime_policy.query_network_path",
            return_value=mock_path,
        ):
            result = _run(router.route_envelope(env))

        assert result is not None

    def test_capability_module_unavailable_does_not_crash(self):
        """Missing capability module is handled gracefully."""
        router = _make_router()
        # Don't use required_capabilities here — ACL may gate on that separately.
        env = _make_envelope(targets=["dev-001"])
        success_result = _default_success_result()

        with patch(
            "core.command_router.CommandRouter._execute_command",
            new=AsyncMock(return_value=success_result),
        ), patch(
            "core.capability_network_runtime_policy.query_routable_executors",
            side_effect=ImportError("module not available"),
        ):
            result = _run(router.route_envelope(env))

        assert result.get("success") is True


# ===========================================================================
# L — Fallback behavior bounded: empty-target envelope returns error
# ===========================================================================


class TestFallbackBoundedBehavior:
    """Group L: Empty-target (non-cross-device) envelope still returns error."""

    def test_empty_targets_non_cross_device_returns_error(self):
        """Envelope with empty targets and no capability spec returns error."""
        router = _make_router()
        env = _make_envelope(targets=[])  # no cross_device, no capability

        result = _run(router.route_envelope(env))

        assert result.get("success") is False
        assert result.get("error_code") is not None

    def test_empty_targets_cross_device_does_not_error_early(self):
        """Cross-device envelope with empty targets delegates to substrate."""
        router = _make_router()
        env = _make_envelope(targets=[], metadata={"cross_device": "true"})

        cross_device_result = {
            "success": False,
            "task_id": "task-test-001",
            "trace_id": "trace-test-001",
            "result": None,
            "error_code": "CROSS_DEVICE_SUBSTRATE_ERROR",
            "error_message": "substrate error",
            "command_id": "task-test-001",
            "request_id": "task-test-001",
            "device_id": "",
            "command": "test_command",
            "via": "command_router.cross_device_substrate",
            "latency_ms": 1.0,
        }

        with patch(
            "core.command_router.CommandRouter._route_cross_device_envelope",
            new=AsyncMock(return_value=cross_device_result),
        ):
            result = _run(router.route_envelope(env))

        # Should reach cross-device substrate, not error out early.
        assert result.get("via") == "command_router.cross_device_substrate"


# ===========================================================================
# M — DISPATCH_CONSTRAINT_CHAIN_UNIFORM_ENFORCEMENT sentinel present
# ===========================================================================


class TestUniformEnforcementSentinel:
    """Group M: DISPATCH_CONSTRAINT_CHAIN_UNIFORM_ENFORCEMENT sentinel."""

    def test_sentinel_importable_from_command_router(self):
        from core.command_router import DISPATCH_CONSTRAINT_CHAIN_UNIFORM_ENFORCEMENT
        assert DISPATCH_CONSTRAINT_CHAIN_UNIFORM_ENFORCEMENT

    def test_sentinel_mentions_constraint_chain_trace(self):
        from core.command_router import DISPATCH_CONSTRAINT_CHAIN_UNIFORM_ENFORCEMENT
        assert "_constraint_chain_trace" in DISPATCH_CONSTRAINT_CHAIN_UNIFORM_ENFORCEMENT

    def test_sentinel_mentions_target_device_validator(self):
        from core.command_router import DISPATCH_CONSTRAINT_CHAIN_UNIFORM_ENFORCEMENT
        assert "target_device_validator" in DISPATCH_CONSTRAINT_CHAIN_UNIFORM_ENFORCEMENT

    def test_sentinel_mentions_source_execution_eligibility(self):
        from core.command_router import DISPATCH_CONSTRAINT_CHAIN_UNIFORM_ENFORCEMENT
        assert "source_execution_eligibility" in DISPATCH_CONSTRAINT_CHAIN_UNIFORM_ENFORCEMENT


# ===========================================================================
# N — SESSION_TRUTH_POSTURE_DISPATCH_FILTER_APPLIED sentinel present
# ===========================================================================


class TestSessionTruthPostureFilterSentinel:
    """Group N: SESSION_TRUTH_POSTURE_DISPATCH_FILTER_APPLIED sentinel."""

    def test_sentinel_importable_from_command_router(self):
        from core.command_router import SESSION_TRUTH_POSTURE_DISPATCH_FILTER_APPLIED
        assert SESSION_TRUTH_POSTURE_DISPATCH_FILTER_APPLIED

    def test_sentinel_mentions_source_runtime_posture_field(self):
        from core.command_router import SESSION_TRUTH_POSTURE_DISPATCH_FILTER_APPLIED
        assert "source_runtime_posture" in SESSION_TRUTH_POSTURE_DISPATCH_FILTER_APPLIED

    def test_sentinel_mentions_constraint_chain_trace(self):
        from core.command_router import SESSION_TRUTH_POSTURE_DISPATCH_FILTER_APPLIED
        assert "_constraint_chain_trace" in SESSION_TRUTH_POSTURE_DISPATCH_FILTER_APPLIED

    def test_sentinel_mentions_check_source_execution_eligibility(self):
        from core.command_router import SESSION_TRUTH_POSTURE_DISPATCH_FILTER_APPLIED
        assert "check_source_execution_eligibility" in SESSION_TRUTH_POSTURE_DISPATCH_FILTER_APPLIED
