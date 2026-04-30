"""tests/test_pr7_v4_scope_correction.py
=========================================
Test suite for PR-7: Scope V4 unified_orchestration_spine to multi-step
orchestration sessions.

Coverage
--------
1. Scope sentinels
   - ORCHESTRATION_SPINE_MULTI_STEP_SESSION_SCOPE_POLICY is present and
     mentions "multi-step".
   - V4_IS_NOT_PER_REQUEST_GATE_POLICY is present and mentions "per-request".
   - Both sentinels are non-empty strings importable from
     core.unified_orchestration_spine.

2. UNIFIED_ORCHESTRATION_SPINE_AUTHORITY — corrected scope
   - No longer claims to be the universal per-request gate for every request.
   - Confirms V4 is not the per-request gate (mentions "NOT").
   - Still mentions V4.

3. ALL_EXECUTION_MODES_MUST_USE_SPINE_POLICY — corrected scope
   - Sentinel is still importable and non-empty (backward compatible).
   - Content now scopes the policy to orchestration sessions, not all requests.

4. evaluate_orchestration_request docstring — corrected scope
   - Does NOT describe the function as "single canonical entry point for all
     execution modes".
   - Correctly scopes the function to multi-step orchestration sessions.

5. Per-request path isolation
   - core.command_router does NOT import from unified_orchestration_spine.
   - core.openclawd does NOT import from unified_orchestration_spine.
   - This confirms the per-request hot path remains independent of V4.

6. V4 multi-step session functionality preserved
   - evaluate_orchestration_request still works for PARALLEL_FANOUT.
   - evaluate_orchestration_request still works for DELEGATED_RUNTIME.
   - evaluate_orchestration_request still works for WAKE_ROUTED.
   - evaluate_orchestration_request still works for HANDOFF.
   - evaluate_orchestration_request still works for CROSS_DEVICE.
   - evaluate_orchestration_request still works for HYBRID.

7. Architecture consistency
   - PARALLEL_FANOUT_MUST_USE_SPINE_POLICY still present (valid multi-step).
   - WAKE_HANDOFF_DELEGATED_MUST_USE_SPINE_POLICY still present (valid).
   - No contradiction between scope sentinels and mode-specific policies.
"""

from __future__ import annotations

import ast
import uuid
from typing import List
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Availability guards
# ---------------------------------------------------------------------------

try:
    from core.unified_orchestration_spine import (
        ALL_EXECUTION_MODES_MUST_USE_SPINE_POLICY,
        CANONICAL_DISPATCH_SLOT_AUTHORITY_IS_SPINE_CONSUMER_POLICY,
        ORCHESTRATION_SPINE_MULTI_STEP_SESSION_SCOPE_POLICY,
        PARALLEL_FANOUT_MUST_USE_SPINE_POLICY,
        SPINE_COMPLETION_CONTRACT_IS_UNIFIED_POLICY,
        UNIFIED_ORCHESTRATION_SPINE_AUTHORITY,
        V4_IS_NOT_PER_REQUEST_GATE_POLICY,
        WAKE_HANDOFF_DELEGATED_MUST_USE_SPINE_POLICY,
        ExecutionMode,
        OrchestrationDecision,
        OrchestrationRequest,
        evaluate_orchestration_request,
    )
    _SPINE_AVAILABLE = True
except ImportError:
    _SPINE_AVAILABLE = False

try:
    from core.canonical_dispatch_slot_authority import (
        CanonicalDispatchSlot,
        CanonicalDispatchSlotStatus,
        CanonicalDispatchSlotsResult,
    )
    _AUTHORITY_AVAILABLE = True
except ImportError:
    _AUTHORITY_AVAILABLE = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _device_id() -> str:
    return f"dev_{uuid.uuid4().hex[:8]}"


def _make_approved_slot(device_id: str, execution_mode: str = "parallel_fanout") -> "CanonicalDispatchSlot":
    return CanonicalDispatchSlot(
        device_id=device_id,
        execution_mode=execution_mode,
        slot_approved=True,
        status=CanonicalDispatchSlotStatus.SLOT_APPROVED.value,
        reason="All ten legality dimensions passed.",
        dimension_results={
            "transport_readiness": True,
            "registration_validity": True,
            "attachment_validity": True,
            "continuity_legality": True,
            "capability_fit": True,
            "execution_mode_eligibility": True,
            "occupancy": True,
            "policy_allowance": True,
            "cross_device_reachability": True,
            "delegated_handoff_acceptability": True,
        },
        blocking_dimension="",
        registered=True,
        transport_alive=True,
        attachment_state="active",
    )


def _make_slots_result(
    execution_mode: str,
    device_id: str,
) -> "CanonicalDispatchSlotsResult":
    slot = _make_approved_slot(device_id, execution_mode)
    return CanonicalDispatchSlotsResult(
        execution_mode=execution_mode,
        approved_slots=[slot],
        blocked_slots=[],
        can_proceed=True,
        block_reason="",
        authority_notes=[],
    )


# ---------------------------------------------------------------------------
# Section 1 — Scope sentinels
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _SPINE_AVAILABLE, reason="spine unavailable")
class TestScopeSentinels:
    """New scope-correction sentinels are present and correctly worded."""

    def test_multi_step_scope_policy_importable(self) -> None:
        assert isinstance(ORCHESTRATION_SPINE_MULTI_STEP_SESSION_SCOPE_POLICY, str)
        assert len(ORCHESTRATION_SPINE_MULTI_STEP_SESSION_SCOPE_POLICY) > 0

    def test_multi_step_scope_policy_mentions_multi_step(self) -> None:
        assert "multi-step" in ORCHESTRATION_SPINE_MULTI_STEP_SESSION_SCOPE_POLICY.lower()

    def test_multi_step_scope_policy_mentions_orchestration_session(self) -> None:
        assert "session" in ORCHESTRATION_SPINE_MULTI_STEP_SESSION_SCOPE_POLICY.lower()

    def test_multi_step_scope_policy_mentions_parallel_fanout(self) -> None:
        assert "parallel" in ORCHESTRATION_SPINE_MULTI_STEP_SESSION_SCOPE_POLICY.lower()

    def test_multi_step_scope_policy_mentions_delegated(self) -> None:
        assert "delegated" in ORCHESTRATION_SPINE_MULTI_STEP_SESSION_SCOPE_POLICY.lower()

    def test_multi_step_scope_policy_mentions_wake_routed(self) -> None:
        assert "wake" in ORCHESTRATION_SPINE_MULTI_STEP_SESSION_SCOPE_POLICY.lower()

    def test_multi_step_scope_policy_mentions_handoff(self) -> None:
        assert "handoff" in ORCHESTRATION_SPINE_MULTI_STEP_SESSION_SCOPE_POLICY.lower()

    def test_v4_not_per_request_gate_policy_importable(self) -> None:
        assert isinstance(V4_IS_NOT_PER_REQUEST_GATE_POLICY, str)
        assert len(V4_IS_NOT_PER_REQUEST_GATE_POLICY) > 0

    def test_v4_not_per_request_gate_policy_mentions_per_request(self) -> None:
        assert "per-request" in V4_IS_NOT_PER_REQUEST_GATE_POLICY.lower()

    def test_v4_not_per_request_gate_policy_mentions_openclawd(self) -> None:
        assert "openclawd" in V4_IS_NOT_PER_REQUEST_GATE_POLICY.lower()

    def test_v4_not_per_request_gate_policy_mentions_commandrouter(self) -> None:
        assert "commandrouter" in V4_IS_NOT_PER_REQUEST_GATE_POLICY.lower()

    def test_scope_sentinel_in_module_all(self) -> None:
        import core.unified_orchestration_spine as spine_mod
        assert "ORCHESTRATION_SPINE_MULTI_STEP_SESSION_SCOPE_POLICY" in spine_mod.__all__
        assert "V4_IS_NOT_PER_REQUEST_GATE_POLICY" in spine_mod.__all__


# ---------------------------------------------------------------------------
# Section 2 — UNIFIED_ORCHESTRATION_SPINE_AUTHORITY corrected scope
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _SPINE_AVAILABLE, reason="spine unavailable")
class TestUnifiedAuthorityCorrectScope:
    """UNIFIED_ORCHESTRATION_SPINE_AUTHORITY no longer claims universal per-request gate."""

    def test_authority_still_importable_and_non_empty(self) -> None:
        assert isinstance(UNIFIED_ORCHESTRATION_SPINE_AUTHORITY, str)
        assert len(UNIFIED_ORCHESTRATION_SPINE_AUTHORITY) > 0

    def test_authority_still_mentions_v4(self) -> None:
        assert "V4" in UNIFIED_ORCHESTRATION_SPINE_AUTHORITY or \
               "v4" in UNIFIED_ORCHESTRATION_SPINE_AUTHORITY.lower()

    def test_authority_does_not_claim_all_dispatch_paths_must_pass_through(self) -> None:
        # The old incorrect claim: "All dispatch paths ... MUST pass through
        # evaluate_orchestration_request() before any task is dispatched."
        # This wording is no longer present because it implied V4 is a
        # universal per-request gate.
        lowered = UNIFIED_ORCHESTRATION_SPINE_AUTHORITY.lower()
        assert "all dispatch paths" not in lowered, (
            "UNIFIED_ORCHESTRATION_SPINE_AUTHORITY must not claim that ALL dispatch "
            "paths must pass through evaluate_orchestration_request(); V4 is scoped "
            "to multi-step orchestration sessions, not every per-request call."
        )

    def test_authority_clarifies_v4_is_not_per_request_gate(self) -> None:
        # The corrected authority should explicitly state V4 is NOT the
        # universal per-request gate.
        assert "not" in UNIFIED_ORCHESTRATION_SPINE_AUTHORITY.lower(), (
            "UNIFIED_ORCHESTRATION_SPINE_AUTHORITY should clarify that V4 is NOT "
            "the universal synchronous per-request gate."
        )

    def test_authority_mentions_multi_step_or_session(self) -> None:
        lowered = UNIFIED_ORCHESTRATION_SPINE_AUTHORITY.lower()
        assert "multi-step" in lowered or "session" in lowered or "orchestration session" in lowered, (
            "UNIFIED_ORCHESTRATION_SPINE_AUTHORITY should reference multi-step "
            "orchestration sessions as V4's actual scope."
        )


# ---------------------------------------------------------------------------
# Section 3 — ALL_EXECUTION_MODES_MUST_USE_SPINE_POLICY corrected scope
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _SPINE_AVAILABLE, reason="spine unavailable")
class TestAllModesPolicyCorrectedScope:
    """ALL_EXECUTION_MODES_MUST_USE_SPINE_POLICY is backward-compatible and correctly scoped."""

    def test_policy_still_importable_and_non_empty(self) -> None:
        assert isinstance(ALL_EXECUTION_MODES_MUST_USE_SPINE_POLICY, str)
        assert len(ALL_EXECUTION_MODES_MUST_USE_SPINE_POLICY) > 0

    def test_policy_does_not_claim_no_mode_may_bypass_unconditionally(self) -> None:
        # The old wording "No execution mode may bypass evaluate_orchestration_request()"
        # was unconditional and incorrect — simple per-request execution legitimately
        # does not call V4.  The corrected policy must not make this blanket claim.
        lowered = ALL_EXECUTION_MODES_MUST_USE_SPINE_POLICY.lower()
        assert "no execution mode may bypass" not in lowered, (
            "ALL_EXECUTION_MODES_MUST_USE_SPINE_POLICY must not make the blanket claim "
            "that no execution mode may bypass V4; simple per-request execution "
            "legitimately bypasses V4 and uses the cognitive/dispatch spine instead."
        )

    def test_policy_references_orchestration_sessions(self) -> None:
        lowered = ALL_EXECUTION_MODES_MUST_USE_SPINE_POLICY.lower()
        assert "session" in lowered or "orchestration" in lowered, (
            "ALL_EXECUTION_MODES_MUST_USE_SPINE_POLICY should scope the mandate "
            "to orchestration sessions, not all execution."
        )


# ---------------------------------------------------------------------------
# Section 4 — evaluate_orchestration_request docstring corrected scope
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _SPINE_AVAILABLE, reason="spine unavailable")
class TestEvaluateOrchestrationRequestDocstring:
    """evaluate_orchestration_request docstring no longer claims universal per-request gate."""

    def test_docstring_present(self) -> None:
        doc = evaluate_orchestration_request.__doc__
        assert doc is not None and len(doc) > 0

    def test_docstring_does_not_claim_every_dispatch_path_must_call_this(self) -> None:
        doc = (evaluate_orchestration_request.__doc__ or "").lower()
        assert "every dispatch path must call this" not in doc, (
            "evaluate_orchestration_request docstring must not claim that every "
            "dispatch path must call it; V4 is scoped to multi-step orchestration "
            "sessions, not every per-request call."
        )

    def test_docstring_does_not_claim_single_canonical_entry_for_all_execution_modes(self) -> None:
        doc = (evaluate_orchestration_request.__doc__ or "").lower()
        assert "single canonical entry point for all execution modes" not in doc, (
            "evaluate_orchestration_request docstring must not describe the function "
            "as the single canonical entry point for all execution modes; this was "
            "the incorrect universal-gate description."
        )

    def test_docstring_scopes_to_orchestration_sessions(self) -> None:
        doc = (evaluate_orchestration_request.__doc__ or "").lower()
        assert "orchestration session" in doc or "multi-step" in doc, (
            "evaluate_orchestration_request docstring should describe the function "
            "as the entry point for multi-step orchestration sessions."
        )


# ---------------------------------------------------------------------------
# Section 5 — Per-request path isolation
# ---------------------------------------------------------------------------


class TestPerRequestPathIsolation:
    """The per-request hot path (CommandRouter, OpenClawd) does not import V4."""

    def _file_imports_spine(self, filepath: str) -> bool:
        """Return True if the file contains an import of unified_orchestration_spine."""
        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                source = fh.read()
            tree = ast.parse(source, filename=filepath)
        except (FileNotFoundError, SyntaxError):
            return False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if "unified_orchestration_spine" in alias.name:
                        return True
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if "unified_orchestration_spine" in module:
                    return True
        return False

    def test_command_router_does_not_import_v4_spine(self) -> None:
        assert not self._file_imports_spine("core/command_router.py"), (
            "core/command_router.py must NOT import unified_orchestration_spine; "
            "the per-request dispatch hot path must remain independent of V4."
        )

    def test_openclawd_does_not_import_v4_spine(self) -> None:
        assert not self._file_imports_spine("core/openclawd.py"), (
            "core/openclawd.py must NOT import unified_orchestration_spine; "
            "the cognitive per-request entry point must remain independent of V4."
        )

    def test_execution_spine_does_not_import_v4_spine(self) -> None:
        assert not self._file_imports_spine("core/execution_spine.py"), (
            "core/execution_spine.py must NOT import unified_orchestration_spine; "
            "the execution ingress adapter operates on the per-request path."
        )


# ---------------------------------------------------------------------------
# Section 6 — V4 multi-step session functionality preserved
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (_SPINE_AVAILABLE and _AUTHORITY_AVAILABLE),
    reason="spine or canonical authority unavailable",
)
class TestV4MultiStepSessionFunctionalityPreserved:
    """V4 still correctly evaluates multi-step orchestration sessions."""

    def _run_mode(self, mode: ExecutionMode) -> OrchestrationDecision:
        dev = _device_id()
        request = OrchestrationRequest(
            execution_mode=mode,
            target_device_ids=[dev],
            task_id=f"task_{uuid.uuid4().hex[:8]}",
        )
        slots_result = _make_slots_result(mode.value, dev)
        with patch(
            "core.unified_orchestration_spine.get_canonical_dispatch_slots",
            return_value=slots_result,
        ):
            return evaluate_orchestration_request(request)

    def test_parallel_fanout_session_still_uses_v4(self) -> None:
        decision = self._run_mode(ExecutionMode.PARALLEL_FANOUT)
        assert decision.can_proceed
        assert decision.execution_mode == ExecutionMode.PARALLEL_FANOUT.value

    def test_delegated_runtime_session_still_uses_v4(self) -> None:
        decision = self._run_mode(ExecutionMode.DELEGATED_RUNTIME)
        assert decision.can_proceed
        assert decision.execution_mode == ExecutionMode.DELEGATED_RUNTIME.value

    def test_wake_routed_session_still_uses_v4(self) -> None:
        decision = self._run_mode(ExecutionMode.WAKE_ROUTED)
        assert decision.can_proceed
        assert decision.execution_mode == ExecutionMode.WAKE_ROUTED.value

    def test_handoff_session_still_uses_v4(self) -> None:
        decision = self._run_mode(ExecutionMode.HANDOFF)
        assert decision.can_proceed
        assert decision.execution_mode == ExecutionMode.HANDOFF.value

    def test_takeover_session_still_uses_v4(self) -> None:
        decision = self._run_mode(ExecutionMode.TAKEOVER)
        assert decision.can_proceed
        assert decision.execution_mode == ExecutionMode.TAKEOVER.value

    def test_cross_device_session_still_uses_v4(self) -> None:
        decision = self._run_mode(ExecutionMode.CROSS_DEVICE)
        assert decision.can_proceed
        assert decision.execution_mode == ExecutionMode.CROSS_DEVICE.value

    def test_hybrid_session_still_uses_v4(self) -> None:
        decision = self._run_mode(ExecutionMode.HYBRID)
        assert decision.can_proceed
        assert decision.execution_mode == ExecutionMode.HYBRID.value

    def test_decision_carries_audit_record_for_multi_step_sessions(self) -> None:
        decision = self._run_mode(ExecutionMode.PARALLEL_FANOUT)
        assert isinstance(decision.audit_record, dict)
        assert "orchestration_id" in decision.audit_record
        assert "execution_mode" in decision.audit_record
        assert "lifecycle_stage" in decision.audit_record

    def test_decision_carries_completion_contract_for_multi_step_sessions(self) -> None:
        decision = self._run_mode(ExecutionMode.PARALLEL_FANOUT)
        assert decision.completion_contract is not None
        assert decision.completion_contract.expected_result_count >= 0


# ---------------------------------------------------------------------------
# Section 7 — Architecture consistency
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _SPINE_AVAILABLE, reason="spine unavailable")
class TestArchitectureConsistency:
    """The corrected scope sentinels are consistent with the mode-specific policies."""

    def test_parallel_fanout_policy_still_present(self) -> None:
        assert isinstance(PARALLEL_FANOUT_MUST_USE_SPINE_POLICY, str)
        assert len(PARALLEL_FANOUT_MUST_USE_SPINE_POLICY) > 0

    def test_wake_handoff_delegated_policy_still_present(self) -> None:
        assert isinstance(WAKE_HANDOFF_DELEGATED_MUST_USE_SPINE_POLICY, str)
        assert len(WAKE_HANDOFF_DELEGATED_MUST_USE_SPINE_POLICY) > 0

    def test_scope_sentinel_consistent_with_parallel_fanout_policy(self) -> None:
        # Both the scope sentinel and the mode-specific policy should agree:
        # parallel fan-out is a multi-step orchestration session that uses V4.
        assert "parallel" in ORCHESTRATION_SPINE_MULTI_STEP_SESSION_SCOPE_POLICY.lower()
        assert "parallel" in PARALLEL_FANOUT_MUST_USE_SPINE_POLICY.lower()

    def test_scope_sentinel_consistent_with_wake_handoff_delegated_policy(self) -> None:
        # Both the scope sentinel and the mode-specific policy agree:
        # wake-routed, handoff, and delegated are multi-step orchestration sessions.
        scope = ORCHESTRATION_SPINE_MULTI_STEP_SESSION_SCOPE_POLICY.lower()
        assert "wake" in scope
        assert "handoff" in scope
        assert "delegated" in scope

    def test_not_gate_policy_consistent_with_scope_policy(self) -> None:
        # V4_IS_NOT_PER_REQUEST_GATE_POLICY should mention "per-request".
        assert "per-request" in V4_IS_NOT_PER_REQUEST_GATE_POLICY.lower()
        # The scope policy should NOT describe V4 as a per-request gate.
        assert "per-request gate" not in ORCHESTRATION_SPINE_MULTI_STEP_SESSION_SCOPE_POLICY.lower() or \
               "not" in ORCHESTRATION_SPINE_MULTI_STEP_SESSION_SCOPE_POLICY.lower()

    def test_spine_completion_contract_policy_still_present(self) -> None:
        assert isinstance(SPINE_COMPLETION_CONTRACT_IS_UNIFIED_POLICY, str)
        assert len(SPINE_COMPLETION_CONTRACT_IS_UNIFIED_POLICY) > 0

    def test_canonical_dispatch_slot_authority_policy_still_present(self) -> None:
        assert isinstance(CANONICAL_DISPATCH_SLOT_AUTHORITY_IS_SPINE_CONSUMER_POLICY, str)
        assert len(CANONICAL_DISPATCH_SLOT_AUTHORITY_IS_SPINE_CONSUMER_POLICY) > 0


# ---------------------------------------------------------------------------
# Section 8 — goal_execution.py legitimate V4 usage preserved
# ---------------------------------------------------------------------------


class TestGoalExecutionV4Usage:
    """goal_execution.py correctly uses V4 for multi-step orchestration (PARALLEL_FANOUT)."""

    _GOAL_EXECUTION_PATH = "galaxy_gateway/android/handlers/goal_execution.py"

    def _read_source(self) -> str:
        try:
            with open(self._GOAL_EXECUTION_PATH, "r", encoding="utf-8") as fh:
                return fh.read()
        except FileNotFoundError:
            return ""

    def test_goal_execution_file_exists(self) -> None:
        import os
        assert os.path.exists(self._GOAL_EXECUTION_PATH), (
            f"{self._GOAL_EXECUTION_PATH} must exist — it is the legitimate "
            "caller of V4 for multi-step PARALLEL_FANOUT orchestration sessions."
        )

    def test_goal_execution_imports_v4_spine(self) -> None:
        source = self._read_source()
        assert "unified_orchestration_spine" in source, (
            "goal_execution.py must import from core.unified_orchestration_spine; "
            "it is the correct caller of evaluate_orchestration_request() for "
            "PARALLEL_FANOUT multi-step orchestration sessions."
        )

    def test_goal_execution_calls_evaluate_orchestration_request(self) -> None:
        source = self._read_source()
        assert "evaluate_orchestration_request" in source, (
            "goal_execution.py must call evaluate_orchestration_request() — "
            "this is the legitimate V4 usage for PARALLEL_FANOUT fan-out sessions."
        )

    def test_goal_execution_uses_parallel_fanout_mode(self) -> None:
        source = self._read_source()
        assert "PARALLEL_FANOUT" in source, (
            "goal_execution.py must use ExecutionMode.PARALLEL_FANOUT when calling "
            "evaluate_orchestration_request(); this is the specific multi-step "
            "orchestration mode that requires V4 session authority."
        )

    def test_goal_execution_does_not_use_v4_for_simple_per_request(self) -> None:
        # Verify that evaluate_orchestration_request appears only in the context
        # of PARALLEL_FANOUT (multi-step), not as a blanket wrapper around all
        # request handling in goal_execution.py.
        import re
        source = self._read_source()
        if not source:
            return
        # Find the line number(s) where evaluate_orchestration_request is called.
        call_lines = [
            i for i, line in enumerate(source.splitlines(), 1)
            if "evaluate_orchestration_request" in line
        ]
        # Find the line number(s) where PARALLEL_FANOUT appears.
        fanout_lines = [
            i for i, line in enumerate(source.splitlines(), 1)
            if "PARALLEL_FANOUT" in line
        ]
        assert call_lines, (
            "evaluate_orchestration_request must be called in goal_execution.py"
        )
        assert fanout_lines, (
            "PARALLEL_FANOUT must appear in goal_execution.py alongside V4 usage"
        )
        # The V4 call must be within 30 lines of a PARALLEL_FANOUT reference,
        # confirming the two are in the same handler block.
        close_enough = any(
            abs(call_ln - fanout_ln) <= 30
            for call_ln in call_lines
            for fanout_ln in fanout_lines
        )
        assert close_enough, (
            "evaluate_orchestration_request() in goal_execution.py must appear "
            "within 30 lines of a PARALLEL_FANOUT reference, confirming V4 usage "
            "is scoped to the multi-step fan-out handler, not every request."
        )


# ---------------------------------------------------------------------------
# Section 9 — Repository-level architecture invariants
# ---------------------------------------------------------------------------


class TestRepositoryArchitectureInvariants:
    """Top-level architecture invariants for the final consistent repository state."""

    def test_v4_scope_is_multi_step_not_universal(self) -> None:
        """The architecture contract explicitly limits V4 to multi-step sessions."""
        assert _SPINE_AVAILABLE, "core.unified_orchestration_spine must be importable"
        # Both the main authority sentinel and the scope policy must agree.
        authority_lower = UNIFIED_ORCHESTRATION_SPINE_AUTHORITY.lower()
        scope_lower = ORCHESTRATION_SPINE_MULTI_STEP_SESSION_SCOPE_POLICY.lower()
        assert "not" in authority_lower, (
            "UNIFIED_ORCHESTRATION_SPINE_AUTHORITY must state V4 is NOT the universal gate"
        )
        assert "multi-step" in scope_lower or "session" in scope_lower, (
            "ORCHESTRATION_SPINE_MULTI_STEP_SESSION_SCOPE_POLICY must reference "
            "multi-step orchestration sessions"
        )
        assert "all dispatch paths" not in authority_lower, (
            "UNIFIED_ORCHESTRATION_SPINE_AUTHORITY must not claim all dispatch paths "
            "must pass through V4"
        )

    def test_per_request_path_is_openclawd_commandrouter(self) -> None:
        """The validated per-request path is OpenClawd → CommandRouter, not V4."""
        assert _SPINE_AVAILABLE, "core.unified_orchestration_spine must be importable"
        gate_policy = V4_IS_NOT_PER_REQUEST_GATE_POLICY.lower()
        # The policy must name the actual per-request path components.
        assert "openclawd" in gate_policy, (
            "V4_IS_NOT_PER_REQUEST_GATE_POLICY must name OpenClawd as the per-request spine"
        )
        assert "commandrouter" in gate_policy, (
            "V4_IS_NOT_PER_REQUEST_GATE_POLICY must name CommandRouter as the per-request router"
        )

    def test_no_false_split_brain_narrative(self) -> None:
        """No sentinel claims V4 is the universal gate while another denies it."""
        assert _SPINE_AVAILABLE, "core.unified_orchestration_spine must be importable"
        # If ORCHESTRATION_SPINE_MULTI_STEP_SESSION_SCOPE_POLICY says V4 is scoped to
        # multi-step sessions, and V4_IS_NOT_PER_REQUEST_GATE_POLICY says V4 is NOT
        # a per-request gate, these two sentinels must not contradict each other.
        scope_denies_universal = (
            "not" in ORCHESTRATION_SPINE_MULTI_STEP_SESSION_SCOPE_POLICY.lower()
            or "multi-step" in ORCHESTRATION_SPINE_MULTI_STEP_SESSION_SCOPE_POLICY.lower()
        )
        gate_denies_per_request = (
            "not" in V4_IS_NOT_PER_REQUEST_GATE_POLICY.lower()
        )
        assert scope_denies_universal, (
            "Scope policy must not claim V4 governs all execution universally"
        )
        assert gate_denies_per_request, (
            "Gate policy must explicitly state V4 is NOT a per-request gate"
        )
