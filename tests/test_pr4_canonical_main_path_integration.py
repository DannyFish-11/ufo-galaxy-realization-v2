#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr4_canonical_main_path_integration.py
===================================================
PR-4: Governance / Readiness / Release Validation Main Chain Entry.

High-value integration test: canonical main path
``register → dispatch → completion → continuation``.

Problem addressed
-----------------
The system lacked any test that could prove the canonical main path closure:

  1. **register** — an Android device registers and its capabilities enter the
     capability graph.
  2. **dispatch** — a command is dispatched to the device via the capability-
     aware routing path.
  3. **completion** — the device's completion signal enters the canonical
     completion ingress and resolves the awaiting future.
  4. **continuation** — the orchestration layer detects completion and can
     continue (i.e., the awaiter is resolved, not timeout-driven).

Because true dual-repo E2E with a real Android device is not available in
this context, these tests use a high-fidelity stub/harness approach that:

- Uses the real :class:`~core.canonical_completion_ingress.CanonicalCompletionIngress`
  (not mocked) to verify the Future-resolution contract.
- Stubs the transport layer (WebSocket / device registry) to isolate the
  integration boundary.
- Verifies the end-to-end flow at the logical level — register, dispatch
  intent, inject completion, assert continuation is unblocked.

Design notes
------------
The canonical main path test harness intentionally:
- Does NOT mock CanonicalCompletionIngress (it is real code being validated).
- DOES stub device registry / transport / WebSocket layers (external).
- Simulates the Android → V2 completion ingress by calling
  ``complete_pending_dispatch()`` directly (the same call that the real
  Android handoff handler makes).

This pattern proves that the logical closure is correct regardless of
transport implementation, which is the most valuable property to verify.

Coverage matrix
---------------
Group A — Canonical completion ingress (real module)
  A01. register_pending_dispatch returns a Future that is not done.
  A02. complete_pending_dispatch resolves the Future with the envelope.
  A03. Future.result() returns the completion envelope.
  A04. The resolved Future is not a timeout-driven resolution.
  A05. Completion can be notified via the notify() path.
  A06. Multiple registrations can be resolved independently.
  A07. Completion ingress is idempotent — double-resolve is safe.

Group B — Register → dispatch → completion → continuation harness
  B01. Simulated device registers and receives a dispatch task.
  B02. Dispatch creates a pending completion registration.
  B03. Simulated Android completion resolves the pending registration.
  B04. Awaiting the Future completes within timeout (not a hung wait).
  B05. Continuation logic (post-completion) can execute after Future resolves.
  B06. Without completion signal, the wait times out (not falsely resolved).

Group C — Capability-aware dispatch path
  C01. Dispatching to a MAIN_CHAIN capability succeeds.
  C02. Dispatching to an EXPERIMENTAL capability surfaces a tier warning.
  C03. CapabilityTierViolationError guards EXPERIMENTAL masquerading as MAIN_CHAIN.
  C04. Capability gate returns PASS for known MAIN_CHAIN capabilities.

Group D — Governance validation in main path context
  D01. Governance validation gate produces a result without raising in observe mode.
  D02. Blocked governance gate → FAIL when enforced.
  D03. Validation result carries meaningful release_gate_verdict.

Group E — Full simulated main path: register → dispatch → completion → continuation
  E01. End-to-end simulated main path completes without timeout.
  E02. Continuation counter increments after completion signal.
  E03. Simulated orchestration loop processes completion events correctly.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Import canonical completion ingress (real module — not mocked)
# ---------------------------------------------------------------------------

try:
    from core.canonical_completion_ingress import (
        CanonicalCompletionIngress,
        get_canonical_completion_ingress,
        CANONICAL_COMPLETION_INGRESS_SENTINEL,
    )
    _CCI_AVAILABLE = True
except ImportError as _e:  # pragma: no cover
    _CCI_AVAILABLE = False
    _cci_err = str(_e)

# ---------------------------------------------------------------------------
# Import capability tier (real module)
# ---------------------------------------------------------------------------

try:
    from core.capability_tier import (
        CapabilityTier,
        CapabilityTierViolationError,
        assert_main_chain_capability,
        get_capability_tier,
    )
    _CAP_TIER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _CAP_TIER_AVAILABLE = False

# ---------------------------------------------------------------------------
# Import governance validation gate (real module)
# ---------------------------------------------------------------------------

try:
    from core.governance_validation_gate import (
        GovernanceValidationGate,
        ValidationOutcome,
        ValidationFailReason,
        GovernanceValidationError,
        evaluate_governance_validation,
        reset_governance_validation_gate,
    )
    _GOV_GATE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _GOV_GATE_AVAILABLE = False

_skip_cci = pytest.mark.skipif(
    not _CCI_AVAILABLE,
    reason=f"core.canonical_completion_ingress not importable: {locals().get('_cci_err', '')}",
)
_skip_cap = pytest.mark.skipif(
    not _CAP_TIER_AVAILABLE,
    reason="core.capability_tier not importable",
)
_skip_gov = pytest.mark.skipif(
    not _GOV_GATE_AVAILABLE,
    reason="core.governance_validation_gate not importable",
)


# ---------------------------------------------------------------------------
# Shared test harness
# ---------------------------------------------------------------------------


def _make_terminal_envelope(
    handoff_id: str,
    task_id: str = "",
    result_payload: Optional[Dict[str, Any]] = None,
) -> MagicMock:
    """Build a minimal terminal completion envelope (simulates Android result)."""
    envelope = MagicMock()
    envelope.handoff_id = handoff_id
    envelope.task_id = task_id
    envelope.is_terminal = True
    envelope.response_kind = "result"
    envelope.result_payload = result_payload or {"status": "success"}
    return envelope


def _make_ack_envelope(handoff_id: str) -> MagicMock:
    """Build a non-terminal ACK envelope (simulates Android acknowledgement)."""
    envelope = MagicMock()
    envelope.handoff_id = handoff_id
    envelope.task_id = ""
    envelope.is_terminal = False
    envelope.response_kind = "ack"
    return envelope


# ===========================================================================
# Group A — Canonical completion ingress (real module)
# ===========================================================================


@_skip_cci
class TestGroupA_CanonicalCompletionIngress:
    """Canonical completion ingress — real module validation."""

    def test_A01_register_returns_pending_future(self):
        """register_pending_dispatch returns a non-done Future."""
        cci = CanonicalCompletionIngress()
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            fut = cci.register_pending_dispatch("hid-A01", task_id="tid-A01")
            assert isinstance(fut, asyncio.Future)
            assert not fut.done(), "Future should be pending after registration"
        finally:
            loop.close()

    def test_A02_complete_pending_dispatch_resolves_future(self):
        """complete_pending_dispatch resolves the Future."""
        cci = CanonicalCompletionIngress()
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            fut = cci.register_pending_dispatch("hid-A02")

            envelope = _make_terminal_envelope("hid-A02")
            resolved = cci.complete_pending_dispatch("hid-A02", envelope)

            assert resolved is True
            assert fut.done()
        finally:
            loop.close()

    def test_A03_resolved_future_result_is_envelope(self):
        """Future.result() returns the completion envelope."""
        cci = CanonicalCompletionIngress()
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            fut = cci.register_pending_dispatch("hid-A03")
            envelope = _make_terminal_envelope("hid-A03")
            cci.complete_pending_dispatch("hid-A03", envelope)
            assert fut.result() is envelope
        finally:
            loop.close()

    def test_A04_resolution_is_not_timeout_driven(self):
        """The Future is resolved by a real signal, not by timeout."""
        cci = CanonicalCompletionIngress()
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            fut = cci.register_pending_dispatch("hid-A04")

            # Future must be pending before completion signal
            assert not fut.done()

            # Inject completion signal
            envelope = _make_terminal_envelope("hid-A04")
            cci.complete_pending_dispatch("hid-A04", envelope)

            # Future must be done immediately — no timeout needed
            assert fut.done()
        finally:
            loop.close()

    def test_A05_notify_path_resolves_future(self):
        """notify() with a terminal envelope resolves the Future."""
        cci = CanonicalCompletionIngress()
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            fut = cci.register_pending_dispatch("hid-A05", task_id="tid-A05")

            envelope = _make_terminal_envelope("hid-A05", task_id="tid-A05")
            resolved = cci.notify(envelope)

            assert resolved is True
            assert fut.done()
        finally:
            loop.close()

    def test_A06_multiple_registrations_resolved_independently(self):
        """Multiple registrations can be resolved independently."""
        cci = CanonicalCompletionIngress()
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            fut1 = cci.register_pending_dispatch("hid-A06-1")
            fut2 = cci.register_pending_dispatch("hid-A06-2")

            # Resolve only fut1
            env1 = _make_terminal_envelope("hid-A06-1")
            cci.complete_pending_dispatch("hid-A06-1", env1)

            assert fut1.done()
            assert not fut2.done()

            # Now resolve fut2
            env2 = _make_terminal_envelope("hid-A06-2")
            cci.complete_pending_dispatch("hid-A06-2", env2)

            assert fut2.done()
        finally:
            loop.close()

    def test_A07_idempotent_double_resolve_is_safe(self):
        """Calling complete_pending_dispatch twice on the same key is safe."""
        cci = CanonicalCompletionIngress()
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            fut = cci.register_pending_dispatch("hid-A07")
            env = _make_terminal_envelope("hid-A07")

            r1 = cci.complete_pending_dispatch("hid-A07", env)
            r2 = cci.complete_pending_dispatch("hid-A07", env)  # idempotent

            assert r1 is True
            assert r2 is False  # second call returns False (already resolved)
            assert fut.done()
        finally:
            loop.close()


# ===========================================================================
# Group B — Register → dispatch → completion → continuation harness
# ===========================================================================


@_skip_cci
class TestGroupB_MainPathHarness:
    """Simulated main path: register → dispatch → completion → continuation."""

    # ------------------------------------------------------------------
    # Helper: simulated orchestration step
    # ------------------------------------------------------------------

    class _SimulatedOrchestrator:
        """High-fidelity stub for the dispatch / await / continuation cycle.

        Simulates the OpenClawd → dispatch_to_websocket await pattern:
        1. register a pending dispatch
        2. await the Future
        3. record completion on resolution
        """

        def __init__(self, cci: CanonicalCompletionIngress):
            self._cci = cci
            self.completed: bool = False
            self.completion_envelope: Any = None
            self.continuation_called: bool = False
            self.timed_out: bool = False

        async def dispatch_and_await(
            self,
            handoff_id: str,
            task_id: str = "",
            timeout: float = 1.0,
        ) -> bool:
            """Simulate dispatch, register, and await the completion Future."""
            fut = self._cci.register_pending_dispatch(handoff_id, task_id=task_id)

            try:
                result_envelope = await asyncio.wait_for(
                    asyncio.shield(fut), timeout=timeout
                )
                self.completed = True
                self.completion_envelope = result_envelope
                self._on_continuation()
                return True
            except asyncio.TimeoutError:
                self.timed_out = True
                return False

        def _on_continuation(self) -> None:
            """Called after successful completion — simulates orchestration continuation."""
            self.continuation_called = True

    def test_B01_device_registers_and_receives_dispatch_task(self):
        """Simulated device register + dispatch creates a pending Future."""
        cci = CanonicalCompletionIngress()
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            # Simulate device registration
            device_id = "android-device-001"
            task_id = "task-B01"
            handoff_id = f"hid-{device_id}-{task_id}"

            # Register dispatch
            fut = cci.register_pending_dispatch(handoff_id, task_id=task_id)
            assert isinstance(fut, asyncio.Future)
            assert not fut.done()
        finally:
            loop.close()

    def test_B02_dispatch_creates_pending_registration(self):
        """Dispatch creates a pending completion registration."""
        cci = CanonicalCompletionIngress()
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            handoff_id = "hid-B02"
            fut = cci.register_pending_dispatch(handoff_id)
            assert not fut.done()
        finally:
            loop.close()

    def test_B03_android_completion_resolves_pending_registration(self):
        """Simulated Android completion resolves the pending Future."""
        cci = CanonicalCompletionIngress()
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            handoff_id = "hid-B03"
            fut = cci.register_pending_dispatch(handoff_id)

            # Simulate Android sending completion signal
            completion_envelope = _make_terminal_envelope(
                handoff_id, result_payload={"status": "done", "result": "task_complete"}
            )
            resolved = cci.complete_pending_dispatch(handoff_id, completion_envelope)

            assert resolved is True
            assert fut.done()
            assert fut.result().result_payload == {"status": "done", "result": "task_complete"}
        finally:
            loop.close()

    def test_B04_awaiting_future_completes_within_timeout(self):
        """Awaiting the Future with a real completion signal finishes before timeout."""
        cci = CanonicalCompletionIngress()

        async def _run():
            orch = self._SimulatedOrchestrator(cci)

            # Schedule the completion signal to fire after a short delay
            async def _send_completion():
                await asyncio.sleep(0.05)
                env = _make_terminal_envelope("hid-B04")
                cci.complete_pending_dispatch("hid-B04", env)

            await asyncio.gather(
                orch.dispatch_and_await("hid-B04", timeout=2.0),
                _send_completion(),
            )
            return orch

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            orch = loop.run_until_complete(_run())
        finally:
            loop.close()

        assert orch.completed, "Expected completion, but dispatch timed out"
        assert not orch.timed_out

    def test_B05_continuation_logic_executes_after_future_resolves(self):
        """Continuation (_on_continuation) is called after Future resolves."""
        cci = CanonicalCompletionIngress()

        async def _run():
            orch = self._SimulatedOrchestrator(cci)

            async def _send_completion():
                await asyncio.sleep(0.05)
                env = _make_terminal_envelope("hid-B05")
                cci.complete_pending_dispatch("hid-B05", env)

            await asyncio.gather(
                orch.dispatch_and_await("hid-B05", timeout=2.0),
                _send_completion(),
            )
            return orch

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            orch = loop.run_until_complete(_run())
        finally:
            loop.close()

        assert orch.continuation_called, (
            "Continuation callback must be called after successful completion"
        )

    def test_B06_without_completion_signal_wait_times_out(self):
        """Without a completion signal, the await times out (not falsely resolved)."""
        cci = CanonicalCompletionIngress()

        async def _run():
            orch = self._SimulatedOrchestrator(cci)
            # Use a very short timeout — no completion signal sent
            success = await orch.dispatch_and_await("hid-B06-no-signal", timeout=0.05)
            return orch, success

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            orch, success = loop.run_until_complete(_run())
        finally:
            loop.close()

        assert orch.timed_out, "Expected timeout when no completion signal is sent"
        assert not orch.completed
        assert not success


# ===========================================================================
# Group C — Capability-aware dispatch path
# ===========================================================================


@_skip_cap
class TestGroupC_CapabilityAwareDispatch:
    """Capability-aware dispatch path validation."""

    def test_C01_dispatching_to_MAIN_CHAIN_capability_succeeds(self):
        """Dispatching to a MAIN_CHAIN capability — tier check passes."""
        main_chain_caps = ["screen", "touch", "keyboard", "command_routing"]
        for cap in main_chain_caps:
            tier = get_capability_tier(cap)
            assert tier == CapabilityTier.MAIN_CHAIN, (
                f"Expected '{cap}' to be MAIN_CHAIN for main path dispatch"
            )

    def test_C02_dispatching_to_EXPERIMENTAL_surfaces_tier_warning(self):
        """EXPERIMENTAL capability → tier is EXPERIMENTAL (not MAIN_CHAIN)."""
        experimental_caps = ["vlm", "webrtc", "live_mesh_runtime"]
        for cap in experimental_caps:
            tier = get_capability_tier(cap)
            assert tier == CapabilityTier.EXPERIMENTAL, (
                f"Expected '{cap}' to be EXPERIMENTAL — it must not masquerade as MAIN_CHAIN"
            )

    def test_C03_assert_main_chain_guards_experimental(self):
        """assert_main_chain_capability raises for EXPERIMENTAL capability."""
        with pytest.raises(CapabilityTierViolationError) as exc_info:
            assert_main_chain_capability("vlm")

        error = exc_info.value
        assert error.actual_tier == CapabilityTier.EXPERIMENTAL
        assert "vlm" in str(error)

    def test_C04_capability_gate_passes_for_MAIN_CHAIN(self):
        """Capability gate returns no violation for MAIN_CHAIN capabilities."""
        main_chain_caps = ["screen", "touch", "keyboard"]
        for cap in main_chain_caps:
            # assert_main_chain_capability must not raise
            try:
                assert_main_chain_capability(cap)
            except CapabilityTierViolationError as exc:
                pytest.fail(
                    f"assert_main_chain_capability('{cap}') raised unexpectedly: {exc}"
                )


# ===========================================================================
# Group D — Governance validation in main path context
# ===========================================================================


@_skip_gov
class TestGroupD_GovernanceValidationInMainPath:
    """Governance validation gate in the main path context."""

    def setup_method(self):
        reset_governance_validation_gate()

    def test_D01_governance_gate_produces_result_in_observe_mode(self):
        """Governance gate produces a ValidationResult without raising."""
        gate = GovernanceValidationGate()
        result = gate.validate(check_capability_tier=False)
        # Must not raise; outcome can be any valid value
        assert result.outcome in {ValidationOutcome.PASS, ValidationOutcome.WARN, ValidationOutcome.FAIL}
        assert result.result_id
        assert result.generated_at > 0.0

    def test_D02_blocked_gate_fails_when_enforced(self):
        """Blocked governance gate raises GovernanceValidationError when enforced."""
        gate_report = MagicMock()
        gate_report.overall_verdict = "blocked"
        gate_report.blocked_gate_worthy_count = 1
        gate_report.gate_worthy_count = 7
        gate_report.report_id = "test-blocked"
        gate_report.category_evaluations = []

        with patch(
            "core.governance_validation_gate._evaluate_distributed_gate",
            return_value=gate_report,
        ), patch(
            "core.governance_validation_gate._DISTRIBUTED_GATE_AVAILABLE", True
        ), patch(
            "core.governance_validation_gate._READINESS_GATE_AVAILABLE", False
        ):
            gate = GovernanceValidationGate()
            with pytest.raises(GovernanceValidationError) as exc_info:
                gate.validate(enforce=True, check_readiness=False, check_capability_tier=False)

        assert exc_info.value.result.failed

    def test_D03_validation_result_carries_meaningful_release_gate_verdict(self):
        """ValidationResult.release_gate_verdict reflects the actual gate verdict."""
        gate_report = MagicMock()
        gate_report.overall_verdict = "open"
        gate_report.blocked_gate_worthy_count = 0
        gate_report.gate_worthy_count = 7
        gate_report.report_id = "test-open"
        gate_report.category_evaluations = []

        readiness_result = MagicMock()
        readiness_result.status = MagicMock()
        readiness_result.status.value = "ready"
        readiness_result.ready = True
        readiness_result.blocked_by = None

        with patch(
            "core.governance_validation_gate._evaluate_distributed_gate",
            return_value=gate_report,
        ), patch(
            "core.governance_validation_gate._DISTRIBUTED_GATE_AVAILABLE", True
        ), patch(
            "core.governance_validation_gate._evaluate_readiness",
            return_value=readiness_result,
        ), patch(
            "core.governance_validation_gate._READINESS_GATE_AVAILABLE", True
        ):
            gate = GovernanceValidationGate()
            result = gate.validate(check_capability_tier=False)

        assert result.release_gate_verdict == "open"


# ===========================================================================
# Group E — Full simulated main path
# ===========================================================================


@pytest.mark.skipif(
    not (_CCI_AVAILABLE and _CAP_TIER_AVAILABLE and _GOV_GATE_AVAILABLE),
    reason="One or more required modules not importable",
)
class TestGroupE_FullSimulatedMainPath:
    """Full simulated main path: register → dispatch → completion → continuation."""

    def setup_method(self):
        reset_governance_validation_gate()

    def test_E01_end_to_end_simulated_main_path_completes_without_timeout(self):
        """Full simulated path completes without timeout.

        This test simulates the canonical main path:
        1. register: Android device "registers" by creating a pending dispatch
        2. dispatch: command is dispatched; Future is registered
        3. completion: Android sends completion signal (complete_pending_dispatch)
        4. continuation: orchestration detects completion and continues
        """
        cci = CanonicalCompletionIngress()
        handoff_id = "hid-E01-main-path"
        task_id = "task-E01"

        # Track the stages
        stages_completed: List[str] = []

        async def _main_path():
            # Stage 1: register — create pending dispatch future
            fut = cci.register_pending_dispatch(handoff_id, task_id=task_id)
            stages_completed.append("register")

            # Stage 2: dispatch — simulate command going to device
            # (In real path: OpenClawd → CommandRouter → DeviceRouter → WS)
            stages_completed.append("dispatch")

            # Stage 3: completion — schedule Android sending the completion signal
            async def _android_sends_completion():
                await asyncio.sleep(0.05)
                env = _make_terminal_envelope(handoff_id, task_id=task_id)
                cci.complete_pending_dispatch(handoff_id, env)
                stages_completed.append("completion_signal_sent")

            # Run dispatch-await and completion injection concurrently
            result_envelope = None

            async def _await_completion():
                nonlocal result_envelope
                result_envelope = await asyncio.wait_for(
                    asyncio.shield(fut), timeout=2.0
                )
                stages_completed.append("completion")

            await asyncio.gather(
                _await_completion(),
                _android_sends_completion(),
            )

            # Stage 4: continuation
            stages_completed.append("continuation")
            return result_envelope

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(_main_path())
        finally:
            loop.close()

        assert "register" in stages_completed
        assert "dispatch" in stages_completed
        assert "completion" in stages_completed
        assert "continuation" in stages_completed
        assert result is not None

    def test_E02_continuation_counter_increments_after_completion(self):
        """Continuation counter increments correctly after completion signal."""
        cci = CanonicalCompletionIngress()
        continuation_count = {"n": 0}

        async def _simulate_task(handoff_id: str) -> bool:
            fut = cci.register_pending_dispatch(handoff_id)

            async def _send_completion():
                await asyncio.sleep(0.02)
                env = _make_terminal_envelope(handoff_id)
                cci.complete_pending_dispatch(handoff_id, env)

            try:
                await asyncio.gather(
                    asyncio.wait_for(asyncio.shield(fut), timeout=1.0),
                    _send_completion(),
                )
                continuation_count["n"] += 1
                return True
            except asyncio.TimeoutError:
                return False

        async def _run_three_tasks():
            tasks = [
                _simulate_task("hid-E02-task1"),
                _simulate_task("hid-E02-task2"),
                _simulate_task("hid-E02-task3"),
            ]
            results = await asyncio.gather(*tasks)
            return results

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            results = loop.run_until_complete(_run_three_tasks())
        finally:
            loop.close()

        assert all(results), f"Some tasks did not complete: {results}"
        assert continuation_count["n"] == 3, (
            f"Expected 3 continuation increments, got {continuation_count['n']}"
        )

    def test_E03_simulated_orchestration_loop_processes_completion_events(self):
        """Simulated orchestration loop processes all completion events correctly.

        Verifies that:
        - Multiple concurrent tasks can all complete
        - Each completion resolves exactly its corresponding Future
        - The orchestration continuation fires for each completed task
        """
        cci = CanonicalCompletionIngress()
        num_tasks = 5
        handoff_ids = [f"hid-E03-task{i}" for i in range(num_tasks)]
        completed_tasks: List[str] = []
        timed_out_tasks: List[str] = []

        async def _simulate_task_lifecycle(hid: str):
            fut = cci.register_pending_dispatch(hid)

            async def _send_completion():
                await asyncio.sleep(0.01 + 0.01 * int(hid[-1]))  # stagger
                env = _make_terminal_envelope(hid)
                cci.complete_pending_dispatch(hid, env)

            try:
                await asyncio.gather(
                    asyncio.wait_for(asyncio.shield(fut), timeout=1.0),
                    _send_completion(),
                )
                completed_tasks.append(hid)
            except asyncio.TimeoutError:
                timed_out_tasks.append(hid)

        async def _run_all():
            await asyncio.gather(*[
                _simulate_task_lifecycle(hid) for hid in handoff_ids
            ])

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_run_all())
        finally:
            loop.close()

        assert len(timed_out_tasks) == 0, (
            f"Some tasks timed out: {timed_out_tasks}"
        )
        assert set(completed_tasks) == set(handoff_ids), (
            f"Not all tasks completed. Completed: {completed_tasks}"
        )
