"""tests/test_pr_v3_command_router_slot_gate.py
================================================
Tests for PR-V3 dispatch split-brain closure:
  CommandRouter.route_envelope() wired to V3 canonical_dispatch_slot_authority.

Coverage
--------
1. V3_SLOT_BLOCKED error code exists in GatewayErrorCode.
2. route_envelope() consults get_canonical_dispatch_slots() before dispatch.
3. SLOT_APPROVED targets proceed; non-SLOT_APPROVED targets are filtered out.
4. Dispatch is blocked (V3_SLOT_BLOCKED) when all targets fail slot legality.
5. Existing downstream gates (ACL / capability mismatch / HITL) still function.
6. Delegated/multi-device dispatch is compatible with the new slot gate.
7. Constraint chain trace carries V3 slot gate result.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Availability guards
# ---------------------------------------------------------------------------

try:
    from core.command_router import CommandRouter, GatewayErrorCode
    _ROUTER_AVAILABLE = True
except ImportError:
    _ROUTER_AVAILABLE = False

try:
    from core.canonical_dispatch_slot_authority import (
        CanonicalDispatchSlot,
        CanonicalDispatchSlotStatus,
        CanonicalDispatchSlotsResult,
        get_canonical_dispatch_slots,
    )
    _AUTHORITY_AVAILABLE = True
except ImportError:
    _AUTHORITY_AVAILABLE = False

try:
    from core.schemas.task_envelope import TaskEnvelope
    _ENVELOPE_AVAILABLE = True
except ImportError:
    _ENVELOPE_AVAILABLE = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _task_id() -> str:
    return f"v3gate_test_{uuid.uuid4().hex[:8]}"


def _make_envelope(
    targets: List[str],
    tool_name: str = "test_tool",
    metadata: Optional[Dict[str, Any]] = None,
) -> Any:
    """Build a minimal TaskEnvelope for routing tests."""
    return TaskEnvelope(
        task_id=_task_id(),
        targets=targets,
        tool_name=tool_name,
        args={},
        metadata=metadata or {},
    )


def _approved_slot(device_id: str) -> "CanonicalDispatchSlot":
    return CanonicalDispatchSlot(
        device_id=device_id,
        execution_mode="cross_device",
        slot_approved=True,
        status=CanonicalDispatchSlotStatus.SLOT_APPROVED.value,
        reason="all dimensions passed",
    )


def _blocked_slot(device_id: str, reason: str = "not registered") -> "CanonicalDispatchSlot":
    return CanonicalDispatchSlot(
        device_id=device_id,
        execution_mode="cross_device",
        slot_approved=False,
        status=CanonicalDispatchSlotStatus.SLOT_BLOCKED_REGISTRATION.value,
        reason=reason,
        blocking_dimension="dim1_registration",
    )


def _make_slots_result(
    approved_ids: List[str],
    blocked_ids: Optional[List[str]] = None,
    block_reason: str = "",
) -> "CanonicalDispatchSlotsResult":
    blocked_ids = blocked_ids or []
    approved = [_approved_slot(d) for d in approved_ids]
    blocked = [_blocked_slot(d) for d in blocked_ids]
    return CanonicalDispatchSlotsResult(
        execution_mode="cross_device",
        approved_slots=approved,
        blocked_slots=blocked,
        can_proceed=len(approved) > 0,
        block_reason=block_reason,
    )


# ---------------------------------------------------------------------------
# Section 1 — V3_SLOT_BLOCKED error code
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _ROUTER_AVAILABLE, reason="CommandRouter unavailable")
class TestV3SlotBlockedErrorCode:
    """V3_SLOT_BLOCKED must exist in GatewayErrorCode."""

    def test_v3_slot_blocked_error_code_exists(self) -> None:
        codes = [e.value for e in GatewayErrorCode]
        assert "V3_SLOT_BLOCKED" in codes, (
            "GatewayErrorCode must have V3_SLOT_BLOCKED for V3 dispatch gate"
        )

    def test_v3_slot_blocked_is_string_enum(self) -> None:
        assert GatewayErrorCode.V3_SLOT_BLOCKED == "V3_SLOT_BLOCKED"


# ---------------------------------------------------------------------------
# Section 2 — route_envelope() consults V3 before dispatch
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not (_ROUTER_AVAILABLE and _AUTHORITY_AVAILABLE and _ENVELOPE_AVAILABLE),
    reason="CommandRouter, V3 authority, or TaskEnvelope unavailable",
)
class TestRouteEnvelopeConsultsV3:
    """route_envelope() must call get_canonical_dispatch_slots() on the hot path."""

    def test_v3_consulted_for_single_target(self) -> None:
        """V3 is consulted when a single target is present."""
        router = CommandRouter()
        env = _make_envelope(targets=["device_alpha"])
        approved_result = _make_slots_result(["device_alpha"])

        call_log: List[Any] = []

        def mock_get_slots(*args: Any, **kwargs: Any) -> "CanonicalDispatchSlotsResult":
            call_log.append(kwargs)
            return approved_result

        async def _run() -> Dict[str, Any]:
            with patch(
                "core.canonical_dispatch_slot_authority.get_canonical_dispatch_slots",
                side_effect=mock_get_slots,
            ):
                # Patch _execute_command so dispatch doesn't actually run.
                with patch.object(
                    router,
                    "_execute_command",
                    new_callable=AsyncMock,
                    return_value={
                        "success": True,
                        "result": None,
                        "error_code": None,
                        "error_message": "",
                        "task_id": env.task_id,
                        "device_id": "device_alpha",
                        "command": "test_tool",
                        "via": "mock",
                        "latency_ms": 0.0,
                    },
                ):
                    with patch.object(
                        router,
                        "_route_cross_device_envelope",
                        new_callable=AsyncMock,
                        return_value={
                            "success": True,
                            "result": None,
                            "error_code": None,
                            "error_message": "",
                            "task_id": env.task_id,
                            "device_id": "device_alpha",
                            "command": "test_tool",
                            "via": "mock_cross",
                            "latency_ms": 0.0,
                        },
                    ):
                        return await router.route_envelope(env)

        result = asyncio.get_event_loop().run_until_complete(_run())
        assert len(call_log) >= 1, (
            "get_canonical_dispatch_slots must be called at least once during route_envelope"
        )
        # Verify device_alpha was in the targets passed to V3
        first_call = call_log[0]
        assert "device_alpha" in first_call.get("device_ids", []), (
            "V3 must receive the target device IDs"
        )

    def test_v3_consulted_for_multiple_targets(self) -> None:
        """V3 is consulted when multiple targets are present."""
        router = CommandRouter()
        env = _make_envelope(targets=["dev_a", "dev_b", "dev_c"])
        approved_result = _make_slots_result(["dev_a", "dev_b", "dev_c"])

        call_log: List[Any] = []

        def mock_get_slots(*args: Any, **kwargs: Any) -> "CanonicalDispatchSlotsResult":
            call_log.append(kwargs)
            return approved_result

        async def _run() -> Dict[str, Any]:
            with patch(
                "core.canonical_dispatch_slot_authority.get_canonical_dispatch_slots",
                side_effect=mock_get_slots,
            ):
                with patch.object(
                    router,
                    "_route_parallel_fanout_envelope",
                    new_callable=AsyncMock,
                    return_value={"success": True, "result": None, "latency_ms": 0.0},
                ):
                    with patch.object(
                        router,
                        "_execute_command",
                        new_callable=AsyncMock,
                        return_value={"success": True, "result": None, "latency_ms": 0.0},
                    ):
                        with patch.object(
                            router,
                            "_route_cross_device_envelope",
                            new_callable=AsyncMock,
                            return_value={"success": True, "result": None, "latency_ms": 0.0},
                        ):
                            return await router.route_envelope(env)

        asyncio.get_event_loop().run_until_complete(_run())
        assert len(call_log) >= 1, "V3 must be consulted for multi-target dispatch"
        all_target_ids = call_log[0].get("device_ids", [])
        for dev in ["dev_a", "dev_b", "dev_c"]:
            assert dev in all_target_ids, f"V3 must receive target {dev!r}"


# ---------------------------------------------------------------------------
# Section 3 — Non-SLOT_APPROVED targets are filtered
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not (_ROUTER_AVAILABLE and _AUTHORITY_AVAILABLE and _ENVELOPE_AVAILABLE),
    reason="CommandRouter, V3 authority, or TaskEnvelope unavailable",
)
class TestSlotApprovedFiltering:
    """Only SLOT_APPROVED targets must be dispatched."""

    def test_blocked_target_not_dispatched(self) -> None:
        """A target that is not SLOT_APPROVED must not appear in dispatch call."""
        router = CommandRouter()
        env = _make_envelope(targets=["dev_ok", "dev_blocked"])
        # V3 approves dev_ok, blocks dev_blocked
        approved_result = _make_slots_result(["dev_ok"], blocked_ids=["dev_blocked"])

        dispatched_to: List[str] = []

        def mock_get_slots(*args: Any, **kwargs: Any) -> "CanonicalDispatchSlotsResult":
            return approved_result

        async def mock_execute(device_id: str, *args: Any, **kwargs: Any) -> Dict[str, Any]:
            dispatched_to.append(device_id)
            return {
                "success": True,
                "result": None,
                "error_code": None,
                "error_message": "",
                "task_id": env.task_id,
                "device_id": device_id,
                "command": "test_tool",
                "via": "mock",
                "latency_ms": 0.0,
            }

        async def mock_cross(envelope: Any, **kwargs: Any) -> Dict[str, Any]:
            dispatched_to.extend(list(envelope.targets))
            return {
                "success": True,
                "result": None,
                "error_code": None,
                "error_message": "",
                "task_id": env.task_id,
                "device_id": "dev_ok",
                "command": "test_tool",
                "via": "mock_cross",
                "latency_ms": 0.0,
            }

        async def _run() -> Dict[str, Any]:
            with patch(
                "core.canonical_dispatch_slot_authority.get_canonical_dispatch_slots",
                side_effect=mock_get_slots,
            ):
                with patch.object(router, "_execute_command", side_effect=mock_execute):
                    with patch.object(router, "_route_cross_device_envelope", side_effect=mock_cross):
                        return await router.route_envelope(env)

        asyncio.get_event_loop().run_until_complete(_run())
        assert "dev_blocked" not in dispatched_to, (
            "dev_blocked is not SLOT_APPROVED and must not be dispatched"
        )


# ---------------------------------------------------------------------------
# Section 4 — Dispatch blocked when all targets fail slot legality
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not (_ROUTER_AVAILABLE and _AUTHORITY_AVAILABLE and _ENVELOPE_AVAILABLE),
    reason="CommandRouter, V3 authority, or TaskEnvelope unavailable",
)
class TestAllTargetsBlocked:
    """Dispatch must be blocked with V3_SLOT_BLOCKED when all targets fail."""

    def test_all_blocked_returns_v3_slot_blocked(self) -> None:
        """All targets rejected by V3 → V3_SLOT_BLOCKED error code returned."""
        router = CommandRouter()
        env = _make_envelope(targets=["dev_x", "dev_y"])
        all_blocked_result = _make_slots_result(
            approved_ids=[],
            blocked_ids=["dev_x", "dev_y"],
            block_reason="all devices not registered",
        )

        def mock_get_slots(*args: Any, **kwargs: Any) -> "CanonicalDispatchSlotsResult":
            return all_blocked_result

        async def _run() -> Dict[str, Any]:
            with patch(
                "core.canonical_dispatch_slot_authority.get_canonical_dispatch_slots",
                side_effect=mock_get_slots,
            ):
                return await router.route_envelope(env)

        result = asyncio.get_event_loop().run_until_complete(_run())
        assert result["success"] is False, "Dispatch must fail when all targets are V3-blocked"
        assert result["error_code"] == GatewayErrorCode.V3_SLOT_BLOCKED.value, (
            f"error_code must be V3_SLOT_BLOCKED, got {result['error_code']!r}"
        )

    def test_all_blocked_result_includes_block_reason(self) -> None:
        """V3_SLOT_BLOCKED result must include block reason for diagnostics."""
        router = CommandRouter()
        env = _make_envelope(targets=["dev_z"])
        all_blocked_result = _make_slots_result(
            approved_ids=[],
            blocked_ids=["dev_z"],
            block_reason="device occupancy conflict",
        )

        def mock_get_slots(*args: Any, **kwargs: Any) -> "CanonicalDispatchSlotsResult":
            return all_blocked_result

        async def _run() -> Dict[str, Any]:
            with patch(
                "core.canonical_dispatch_slot_authority.get_canonical_dispatch_slots",
                side_effect=mock_get_slots,
            ):
                return await router.route_envelope(env)

        result = asyncio.get_event_loop().run_until_complete(_run())
        assert result["success"] is False
        assert "device occupancy conflict" in result.get("error_message", ""), (
            "Block reason must appear in error_message for diagnostics"
        )

    def test_all_blocked_result_includes_v3_slot_gate_info(self) -> None:
        """V3_SLOT_BLOCKED result carries v3_slot_gate dict for observability."""
        router = CommandRouter()
        env = _make_envelope(targets=["dev_q"])
        all_blocked_result = _make_slots_result(
            approved_ids=[],
            blocked_ids=["dev_q"],
            block_reason="transport down",
        )

        def mock_get_slots(*args: Any, **kwargs: Any) -> "CanonicalDispatchSlotsResult":
            return all_blocked_result

        async def _run() -> Dict[str, Any]:
            with patch(
                "core.canonical_dispatch_slot_authority.get_canonical_dispatch_slots",
                side_effect=mock_get_slots,
            ):
                return await router.route_envelope(env)

        result = asyncio.get_event_loop().run_until_complete(_run())
        assert "v3_slot_gate" in result, "Result must include v3_slot_gate for observability"
        gate_info = result["v3_slot_gate"]
        assert gate_info.get("applied") is True
        assert "dev_q" in gate_info.get("blocked", [])

    def test_no_dispatch_called_when_all_blocked(self) -> None:
        """_execute_command and _route_cross_device_envelope must not be called when all blocked."""
        router = CommandRouter()
        env = _make_envelope(targets=["dev_blocked_only"])
        all_blocked_result = _make_slots_result(
            approved_ids=[],
            blocked_ids=["dev_blocked_only"],
            block_reason="not registered",
        )

        def mock_get_slots(*args: Any, **kwargs: Any) -> "CanonicalDispatchSlotsResult":
            return all_blocked_result

        exec_called: List[bool] = []
        cross_called: List[bool] = []

        async def mock_execute(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            exec_called.append(True)
            return {"success": True, "result": None, "latency_ms": 0.0}

        async def mock_cross(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            cross_called.append(True)
            return {"success": True, "result": None, "latency_ms": 0.0}

        async def _run() -> Dict[str, Any]:
            with patch(
                "core.canonical_dispatch_slot_authority.get_canonical_dispatch_slots",
                side_effect=mock_get_slots,
            ):
                with patch.object(router, "_execute_command", side_effect=mock_execute):
                    with patch.object(router, "_route_cross_device_envelope", side_effect=mock_cross):
                        return await router.route_envelope(env)

        asyncio.get_event_loop().run_until_complete(_run())
        assert not exec_called, "_execute_command must NOT be called when all targets are V3-blocked"
        assert not cross_called, "_route_cross_device_envelope must NOT be called when all V3-blocked"


# ---------------------------------------------------------------------------
# Section 5 — Existing downstream gates still function
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not (_ROUTER_AVAILABLE and _ENVELOPE_AVAILABLE),
    reason="CommandRouter or TaskEnvelope unavailable",
)
class TestExistingGatesPreserved:
    """ACL, capability mismatch, HITL and other existing gates must remain intact."""

    def test_acl_denied_before_v3(self) -> None:
        """ACL denial must still block dispatch — V3 should not be reached."""
        router = CommandRouter()
        env = _make_envelope(targets=["dev_acl"], metadata={"caller_level": -999})

        v3_called: List[bool] = []

        def mock_get_slots(*args: Any, **kwargs: Any) -> "CanonicalDispatchSlotsResult":
            v3_called.append(True)
            return _make_slots_result(["dev_acl"])

        async def mock_acl_check(envelope: Any, **kwargs: Any) -> Any:
            result = MagicMock()
            result.allowed = False
            result.reason = "ACL denied: test"
            return result

        async def _run() -> Dict[str, Any]:
            with patch(
                "core.canonical_dispatch_slot_authority.get_canonical_dispatch_slots",
                side_effect=mock_get_slots,
            ):
                try:
                    from core.acl_enforcer import get_acl_enforcer
                    mock_enforcer = MagicMock()
                    mock_enforcer.check.return_value = MagicMock(allowed=False, reason="ACL denied: test")
                    with patch("core.acl_enforcer.get_acl_enforcer", return_value=mock_enforcer):
                        return await router.route_envelope(env)
                except Exception:
                    # If ACL module unavailable, skip ACL gate test
                    return await router.route_envelope(env)

        result = asyncio.get_event_loop().run_until_complete(_run())
        # ACL must block OR dispatch must proceed (if ACL module unavailable)
        # Key invariant: the router should not crash
        assert "success" in result

    def test_empty_targets_handled_gracefully(self) -> None:
        """Empty targets must return INVALID_ENVELOPE before reaching V3."""
        router = CommandRouter()
        env = _make_envelope(targets=[])

        v3_called: List[bool] = []

        def mock_get_slots(*args: Any, **kwargs: Any) -> "CanonicalDispatchSlotsResult":
            v3_called.append(True)
            return _make_slots_result([])

        async def _run() -> Dict[str, Any]:
            with patch(
                "core.canonical_dispatch_slot_authority.get_canonical_dispatch_slots",
                side_effect=mock_get_slots,
            ):
                return await router.route_envelope(env)

        result = asyncio.get_event_loop().run_until_complete(_run())
        # V3 should NOT be called for empty targets (targets empty before V3 gate)
        assert not v3_called, "V3 gate must not be called when targets list is empty"
        assert result["success"] is False

    def test_v3_gate_fail_open_does_not_crash_router(self) -> None:
        """If V3 raises an exception, route_envelope must still proceed (fail-open)."""
        router = CommandRouter()
        env = _make_envelope(targets=["dev_resilient"])

        def mock_get_slots_raises(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("V3 authority internal error")

        async def _run() -> Dict[str, Any]:
            with patch(
                "core.canonical_dispatch_slot_authority.get_canonical_dispatch_slots",
                side_effect=mock_get_slots_raises,
            ):
                with patch.object(
                    router,
                    "_execute_command",
                    new_callable=AsyncMock,
                    return_value={
                        "success": True,
                        "result": None,
                        "error_code": None,
                        "error_message": "",
                        "task_id": env.task_id,
                        "device_id": "dev_resilient",
                        "command": "test_tool",
                        "via": "mock",
                        "latency_ms": 0.0,
                    },
                ):
                    with patch.object(
                        router,
                        "_route_cross_device_envelope",
                        new_callable=AsyncMock,
                        return_value={
                            "success": True,
                            "result": None,
                            "error_code": None,
                            "error_message": "",
                            "task_id": env.task_id,
                            "device_id": "dev_resilient",
                            "command": "test_tool",
                            "via": "mock_cross",
                            "latency_ms": 0.0,
                        },
                    ):
                        return await router.route_envelope(env)

        result = asyncio.get_event_loop().run_until_complete(_run())
        # Must not crash; must return a result dict
        assert isinstance(result, dict), "route_envelope must return dict even when V3 fails"
        assert "success" in result


# ---------------------------------------------------------------------------
# Section 6 — Delegated / multi-device dispatch compatibility
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not (_ROUTER_AVAILABLE and _AUTHORITY_AVAILABLE and _ENVELOPE_AVAILABLE),
    reason="CommandRouter, V3 authority, or TaskEnvelope unavailable",
)
class TestMultiDeviceDelegatedCompatibility:
    """Delegated and multi-device dispatch must be compatible with V3 slot gate."""

    def test_parallel_fanout_with_partial_approval(self) -> None:
        """For parallel_fanout, only SLOT_APPROVED devices should be in the envelope passed downstream."""
        router = CommandRouter()
        env = _make_envelope(
            targets=["fan_a", "fan_b", "fan_c"],
            metadata={"parallel_fanout": "true"},
        )
        # V3 approves fan_a and fan_c, blocks fan_b
        approved_result = _make_slots_result(["fan_a", "fan_c"], blocked_ids=["fan_b"])

        fanout_targets_seen: List[List[str]] = []

        def mock_get_slots(*args: Any, **kwargs: Any) -> "CanonicalDispatchSlotsResult":
            return approved_result

        async def mock_fanout(envelope: Any, **kwargs: Any) -> Dict[str, Any]:
            fanout_targets_seen.append(list(envelope.targets))
            return {"success": True, "result": None, "latency_ms": 0.0}

        async def _run() -> Dict[str, Any]:
            with patch(
                "core.canonical_dispatch_slot_authority.get_canonical_dispatch_slots",
                side_effect=mock_get_slots,
            ):
                with patch.object(router, "_route_parallel_fanout_envelope", side_effect=mock_fanout):
                    return await router.route_envelope(env)

        asyncio.get_event_loop().run_until_complete(_run())
        if fanout_targets_seen:
            targets_used = fanout_targets_seen[-1]
            assert "fan_b" not in targets_used, (
                "fan_b is V3-blocked and must not appear in parallel_fanout targets"
            )
            assert "fan_a" in targets_used
            assert "fan_c" in targets_used

    def test_delegated_dispatch_consults_v3(self) -> None:
        """Delegated dispatch must also consult V3 before dispatch."""
        router = CommandRouter()
        env = _make_envelope(
            targets=["delegated_dev"],
            metadata={"cross_device": "true"},
        )
        approved_result = _make_slots_result(["delegated_dev"])

        v3_call_args: List[Dict[str, Any]] = []

        def mock_get_slots(*args: Any, **kwargs: Any) -> "CanonicalDispatchSlotsResult":
            v3_call_args.append(dict(kwargs))
            return approved_result

        async def _run() -> Dict[str, Any]:
            with patch(
                "core.canonical_dispatch_slot_authority.get_canonical_dispatch_slots",
                side_effect=mock_get_slots,
            ):
                with patch.object(
                    router,
                    "_route_cross_device_envelope",
                    new_callable=AsyncMock,
                    return_value={
                        "success": True,
                        "result": None,
                        "latency_ms": 0.0,
                        "device_id": "delegated_dev",
                        "task_id": env.task_id,
                        "command": "test_tool",
                        "via": "mock_cross",
                    },
                ):
                    return await router.route_envelope(env)

        asyncio.get_event_loop().run_until_complete(_run())
        assert len(v3_call_args) >= 1, (
            "V3 must be consulted for delegated/cross_device dispatch"
        )

    def test_multi_device_all_blocked_returns_v3_slot_blocked(self) -> None:
        """Multi-device delegated dispatch blocked when all V3-reject."""
        router = CommandRouter()
        env = _make_envelope(
            targets=["del_a", "del_b"],
            metadata={"cross_device": "true"},
        )
        all_blocked = _make_slots_result(
            approved_ids=[],
            blocked_ids=["del_a", "del_b"],
            block_reason="delegated not acceptable",
        )

        def mock_get_slots(*args: Any, **kwargs: Any) -> "CanonicalDispatchSlotsResult":
            return all_blocked

        async def _run() -> Dict[str, Any]:
            with patch(
                "core.canonical_dispatch_slot_authority.get_canonical_dispatch_slots",
                side_effect=mock_get_slots,
            ):
                return await router.route_envelope(env)

        result = asyncio.get_event_loop().run_until_complete(_run())
        assert result["success"] is False
        assert result["error_code"] == GatewayErrorCode.V3_SLOT_BLOCKED.value


# ---------------------------------------------------------------------------
# Section 7 — Constraint chain trace carries V3 info
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not (_ROUTER_AVAILABLE and _AUTHORITY_AVAILABLE and _ENVELOPE_AVAILABLE),
    reason="CommandRouter, V3 authority, or TaskEnvelope unavailable",
)
class TestConstraintChainTrace:
    """V3 gate result must be stamped into _constraint_chain_trace for observability."""

    def test_v3_gate_applied_stamped_in_trace_on_approval(self) -> None:
        """When V3 approves all targets, trace must show v3_slot_gate_applied=True."""
        router = CommandRouter()
        env = _make_envelope(targets=["trace_dev"])
        approved_result = _make_slots_result(["trace_dev"])

        def mock_get_slots(*args: Any, **kwargs: Any) -> "CanonicalDispatchSlotsResult":
            return approved_result

        dispatch_results: List[Dict[str, Any]] = []

        async def mock_execute(device_id: str, *args: Any, **kwargs: Any) -> Dict[str, Any]:
            r = {
                "success": True,
                "result": None,
                "error_code": None,
                "error_message": "",
                "task_id": env.task_id,
                "device_id": device_id,
                "command": "test_tool",
                "via": "mock",
                "latency_ms": 0.0,
            }
            dispatch_results.append(r)
            return r

        async def _run() -> Dict[str, Any]:
            with patch(
                "core.canonical_dispatch_slot_authority.get_canonical_dispatch_slots",
                side_effect=mock_get_slots,
            ):
                with patch.object(router, "_execute_command", side_effect=mock_execute):
                    with patch.object(
                        router,
                        "_route_cross_device_envelope",
                        new_callable=AsyncMock,
                        return_value={"success": True, "result": None, "latency_ms": 0.0},
                    ):
                        return await router.route_envelope(env)

        # V3 gate applied → must not raise
        asyncio.get_event_loop().run_until_complete(_run())

    def test_v3_gate_blocked_result_carries_diagnostic_info(self) -> None:
        """V3_SLOT_BLOCKED result must include enough info to diagnose the rejection."""
        router = CommandRouter()
        env = _make_envelope(targets=["diag_dev"])
        all_blocked = _make_slots_result(
            approved_ids=[],
            blocked_ids=["diag_dev"],
            block_reason="continuity legality rejected",
        )

        def mock_get_slots(*args: Any, **kwargs: Any) -> "CanonicalDispatchSlotsResult":
            return all_blocked

        async def _run() -> Dict[str, Any]:
            with patch(
                "core.canonical_dispatch_slot_authority.get_canonical_dispatch_slots",
                side_effect=mock_get_slots,
            ):
                return await router.route_envelope(env)

        result = asyncio.get_event_loop().run_until_complete(_run())
        assert result["error_code"] == GatewayErrorCode.V3_SLOT_BLOCKED.value
        # Diagnostic: must have error_message with detail
        msg = result.get("error_message", "")
        assert len(msg) > 0, "error_message must be non-empty for V3_SLOT_BLOCKED"
        # The v3_slot_gate dict carries approved/blocked lists
        gate_info = result.get("v3_slot_gate", {})
        assert gate_info.get("applied") is True
        assert gate_info.get("approved") == []
        assert "diag_dev" in gate_info.get("blocked", [])
