"""tests/test_pr_v3_canonical_dispatch_slot_authority.py
=========================================================
Test suite for PR-V3: Canonical Dispatch-Slot Authority.

Coverage
--------
1. Sentinel importability
   - All authority sentinels are non-empty strings.
   - New policy sentinels in unified_dispatch_readiness_gate.
   - New sentinel in unified_orchestration_spine.

2. CanonicalDispatchSlotStatus enum completeness
   - All expected status values are present.
   - Status values are string-valued for serialisation.

3. CanonicalDispatchSlot serialisation
   - to_dict includes all required fields.
   - to_json is valid JSON and round-trips to dict.
   - authority key is present in to_dict.

4. evaluate_canonical_dispatch_slot — happy path
   - Returns SLOT_APPROVED when all sub-checks pass.
   - slot_approved is True for SLOT_APPROVED status.
   - dimension_results contains all expected dimension keys.

5. evaluate_canonical_dispatch_slot — base gate blocking
   - SLOT_BLOCKED_REGISTRATION when device not registered.
   - SLOT_BLOCKED_TRANSPORT when transport down.
   - SLOT_BLOCKED_ATTACHMENT when attachment is stale.

6. evaluate_canonical_dispatch_slot — new dimension blocking
   - SLOT_BLOCKED_CONTINUITY_LEGALITY when continuity authority rejects.
   - SLOT_BLOCKED_EXECUTION_MODE_INELIGIBLE when mode eligibility fails.
   - SLOT_BLOCKED_OCCUPANCY when device is occupied.
   - SLOT_BLOCKED_POLICY when policy rejects.
   - SLOT_BLOCKED_DELEGATED_HANDOFF when acceptance gate rejects.

7. get_canonical_dispatch_slots — multi-device
   - approved_slots contains only SLOT_APPROVED devices.
   - blocked_slots contains devices that failed any dimension.
   - can_proceed is True iff at least one approved slot exists.
   - can_proceed is False when all devices are blocked.

8. Execution modes — all consume the same authority
   - parallel_fanout mode evaluates all target devices.
   - delegated_runtime mode evaluates delegated/handoff acceptability.
   - wake_routed mode evaluates through the authority.
   - handoff mode evaluates through the authority.
   - hybrid mode evaluates through the authority.

9. Error safety
   - evaluate_canonical_dispatch_slot never raises even with bad inputs.
   - get_canonical_dispatch_slots never raises even with empty list.

10. DispatchReadinessStatus new values
    - BLOCKED_CONTINUITY_LEGALITY is present in the enum.
    - BLOCKED_EXECUTION_MODE_INELIGIBLE is present in the enum.
    - BLOCKED_OCCUPANCY is present in the enum.
    - BLOCKED_POLICY is present in the enum.
"""

from __future__ import annotations

import json
import sys
import types
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Availability guards
# ---------------------------------------------------------------------------

try:
    from core.canonical_dispatch_slot_authority import (
        ALL_EXECUTION_MODES_MUST_CONSUME_CANONICAL_SLOT_POLICY,
        CANONICAL_DISPATCH_SLOT_AUTHORITY,
        CANONICAL_DISPATCH_SLOT_PR_V3_SENTINEL,
        CONTINUITY_LEGALITY_GATES_DISPATCH_POLICY,
        DELEGATED_HANDOFF_MUST_USE_LEGAL_SLOT_BINDING_POLICY,
        DEVICE_ROUTER_MUST_NOT_ACT_AS_READINESS_AUTHORITY_POLICY,
        EXECUTION_MODE_ELIGIBILITY_GATES_DISPATCH_POLICY,
        FANOUT_SELECTS_SLOTS_NOT_RAW_DEVICES_POLICY,
        OCCUPANCY_GATES_DISPATCH_POLICY,
        POLICY_ALLOWANCE_GATES_DISPATCH_POLICY,
        WAKE_MUST_NOT_BYPASS_CANONICAL_SLOT_POLICY,
        CanonicalDispatchSlot,
        CanonicalDispatchSlotStatus,
        CanonicalDispatchSlotsResult,
        evaluate_canonical_dispatch_slot,
        get_canonical_dispatch_slots,
    )
    _AUTHORITY_AVAILABLE = True
except ImportError:
    _AUTHORITY_AVAILABLE = False

try:
    from core.unified_dispatch_readiness_gate import (
        CANONICAL_DISPATCH_SLOT_AUTHORITY_CONSUMES_THIS_GATE_POLICY,
        DispatchReadinessStatus,
    )
    _GATE_AVAILABLE = True
except ImportError:
    _GATE_AVAILABLE = False

try:
    from core.unified_orchestration_spine import (
        CANONICAL_DISPATCH_SLOT_AUTHORITY_IS_SPINE_CONSUMER_POLICY,
    )
    _SPINE_AVAILABLE = True
except ImportError:
    _SPINE_AVAILABLE = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _device_id() -> str:
    return f"slot_test_dev_{uuid.uuid4().hex[:8]}"


def _make_ready_gate_result(device_id: str) -> Any:
    """Build a mock DispatchReadinessResult that appears fully ready."""
    from core.unified_dispatch_readiness_gate import (
        DispatchReadinessResult,
        DispatchReadinessStatus,
    )
    return DispatchReadinessResult(
        device_id=device_id,
        dispatch_ready=True,
        registered=True,
        status=DispatchReadinessStatus.DISPATCH_READY.value,
        reason="mock: all base gates passed",
        transport_alive=True,
        attachment_state="active",
        runtime_session_id=f"sess_{uuid.uuid4().hex[:8]}",
        runtime_attachment_session_id=f"attach_{uuid.uuid4().hex[:8]}",
        registration_gaps=[],
        blocking_notes=[],
    )


def _make_blocked_gate_result(device_id: str, status: str, reason: str) -> Any:
    """Build a mock DispatchReadinessResult that blocks at the base gate."""
    from core.unified_dispatch_readiness_gate import DispatchReadinessResult
    return DispatchReadinessResult(
        device_id=device_id,
        dispatch_ready=False,
        registered=(status != "not_registered"),
        status=status,
        reason=reason,
        transport_alive=(status not in ("blocked_transport", "not_registered")),
        attachment_state="active" if status not in ("blocked_stale_attachment",) else "replaced",
        blocking_notes=[reason],
    )


# ---------------------------------------------------------------------------
# Section 1 — Sentinel importability
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _AUTHORITY_AVAILABLE, reason="canonical_dispatch_slot_authority unavailable")
class TestAuthoritysentinel:
    """All canonical dispatch-slot authority sentinels are importable non-empty strings."""

    def test_authority_sentinel_non_empty(self) -> None:
        assert isinstance(CANONICAL_DISPATCH_SLOT_AUTHORITY, str)
        assert len(CANONICAL_DISPATCH_SLOT_AUTHORITY) > 0

    def test_pr_v3_sentinel_non_empty(self) -> None:
        assert isinstance(CANONICAL_DISPATCH_SLOT_PR_V3_SENTINEL, str)
        assert len(CANONICAL_DISPATCH_SLOT_PR_V3_SENTINEL) > 0

    def test_all_modes_must_consume_policy_non_empty(self) -> None:
        assert isinstance(ALL_EXECUTION_MODES_MUST_CONSUME_CANONICAL_SLOT_POLICY, str)
        assert len(ALL_EXECUTION_MODES_MUST_CONSUME_CANONICAL_SLOT_POLICY) > 0

    def test_device_router_policy_non_empty(self) -> None:
        assert isinstance(DEVICE_ROUTER_MUST_NOT_ACT_AS_READINESS_AUTHORITY_POLICY, str)
        assert len(DEVICE_ROUTER_MUST_NOT_ACT_AS_READINESS_AUTHORITY_POLICY) > 0

    def test_wake_bypass_policy_non_empty(self) -> None:
        assert isinstance(WAKE_MUST_NOT_BYPASS_CANONICAL_SLOT_POLICY, str)
        assert len(WAKE_MUST_NOT_BYPASS_CANONICAL_SLOT_POLICY) > 0

    def test_fanout_slots_policy_non_empty(self) -> None:
        assert isinstance(FANOUT_SELECTS_SLOTS_NOT_RAW_DEVICES_POLICY, str)
        assert len(FANOUT_SELECTS_SLOTS_NOT_RAW_DEVICES_POLICY) > 0

    def test_delegated_handoff_policy_non_empty(self) -> None:
        assert isinstance(DELEGATED_HANDOFF_MUST_USE_LEGAL_SLOT_BINDING_POLICY, str)
        assert len(DELEGATED_HANDOFF_MUST_USE_LEGAL_SLOT_BINDING_POLICY) > 0

    def test_continuity_legality_policy_non_empty(self) -> None:
        assert isinstance(CONTINUITY_LEGALITY_GATES_DISPATCH_POLICY, str)
        assert len(CONTINUITY_LEGALITY_GATES_DISPATCH_POLICY) > 0

    def test_execution_mode_eligibility_policy_non_empty(self) -> None:
        assert isinstance(EXECUTION_MODE_ELIGIBILITY_GATES_DISPATCH_POLICY, str)
        assert len(EXECUTION_MODE_ELIGIBILITY_GATES_DISPATCH_POLICY) > 0

    def test_occupancy_policy_non_empty(self) -> None:
        assert isinstance(OCCUPANCY_GATES_DISPATCH_POLICY, str)
        assert len(OCCUPANCY_GATES_DISPATCH_POLICY) > 0

    def test_policy_allowance_sentinel_non_empty(self) -> None:
        assert isinstance(POLICY_ALLOWANCE_GATES_DISPATCH_POLICY, str)
        assert len(POLICY_ALLOWANCE_GATES_DISPATCH_POLICY) > 0


@pytest.mark.skipif(not _GATE_AVAILABLE, reason="unified_dispatch_readiness_gate unavailable")
class TestGateNewSentinel:
    """New sentinel in unified_dispatch_readiness_gate is importable."""

    def test_gate_consumes_slot_authority_policy_non_empty(self) -> None:
        assert isinstance(CANONICAL_DISPATCH_SLOT_AUTHORITY_CONSUMES_THIS_GATE_POLICY, str)
        assert len(CANONICAL_DISPATCH_SLOT_AUTHORITY_CONSUMES_THIS_GATE_POLICY) > 0


@pytest.mark.skipif(not _SPINE_AVAILABLE, reason="unified_orchestration_spine unavailable")
class TestSpineNewSentinel:
    """New sentinel in unified_orchestration_spine is importable."""

    def test_spine_consumer_policy_non_empty(self) -> None:
        assert isinstance(CANONICAL_DISPATCH_SLOT_AUTHORITY_IS_SPINE_CONSUMER_POLICY, str)
        assert len(CANONICAL_DISPATCH_SLOT_AUTHORITY_IS_SPINE_CONSUMER_POLICY) > 0


# ---------------------------------------------------------------------------
# Section 2 — CanonicalDispatchSlotStatus enum completeness
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _AUTHORITY_AVAILABLE, reason="canonical_dispatch_slot_authority unavailable")
class TestSlotStatusEnum:
    """CanonicalDispatchSlotStatus has all required values."""

    _EXPECTED_STATUSES = {
        "slot_approved",
        "slot_blocked_transport",
        "slot_blocked_registration",
        "slot_blocked_attachment",
        "slot_blocked_continuity_legality",
        "slot_blocked_capability",
        "slot_blocked_execution_mode_ineligible",
        "slot_blocked_occupancy",
        "slot_blocked_policy",
        "slot_blocked_cross_device_reachability",
        "slot_blocked_delegated_handoff",
        "slot_not_registered",
        "slot_authority_error",
    }

    def test_all_expected_statuses_present(self) -> None:
        actual = {m.value for m in CanonicalDispatchSlotStatus}
        assert self._EXPECTED_STATUSES <= actual, (
            f"Missing statuses: {self._EXPECTED_STATUSES - actual}"
        )

    def test_statuses_are_strings(self) -> None:
        for member in CanonicalDispatchSlotStatus:
            assert isinstance(member.value, str), (
                f"Status {member.name!r} value is not a string"
            )

    def test_slot_approved_is_the_only_positive_status(self) -> None:
        approved = [m for m in CanonicalDispatchSlotStatus if m.value == "slot_approved"]
        assert len(approved) == 1


# ---------------------------------------------------------------------------
# Section 3 — CanonicalDispatchSlot serialisation
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _AUTHORITY_AVAILABLE, reason="canonical_dispatch_slot_authority unavailable")
class TestSlotSerialisation:
    """CanonicalDispatchSlot to_dict / to_json are stable."""

    _REQUIRED_FIELDS = {
        "device_id", "execution_mode", "slot_approved", "status", "reason",
        "dimension_results", "blocking_dimension", "registered",
        "transport_alive", "attachment_state", "runtime_session_id",
        "runtime_attachment_session_id", "registration_gaps",
        "continuity_verdict", "execution_mode_eligible", "occupancy_clear",
        "policy_allowed", "delegated_handoff_acceptable", "authority_notes",
        "authority",
    }

    def _make_slot(self) -> CanonicalDispatchSlot:
        return CanonicalDispatchSlot(
            device_id="dev_ser_001",
            execution_mode="cross_device",
            slot_approved=True,
            status=CanonicalDispatchSlotStatus.SLOT_APPROVED.value,
            reason="All gates passed.",
            dimension_results={"transport_readiness": True},
            registered=True,
            transport_alive=True,
            attachment_state="active",
            continuity_verdict="allow",
            execution_mode_eligible=True,
            occupancy_clear=True,
            policy_allowed=True,
            delegated_handoff_acceptable=True,
        )

    def test_to_dict_contains_required_fields(self) -> None:
        slot = self._make_slot()
        d = slot.to_dict()
        missing = self._REQUIRED_FIELDS - set(d.keys())
        assert not missing, f"Missing fields in to_dict: {missing}"

    def test_to_dict_authority_is_non_empty(self) -> None:
        slot = self._make_slot()
        d = slot.to_dict()
        assert d["authority"] == CANONICAL_DISPATCH_SLOT_AUTHORITY

    def test_to_json_is_valid_json(self) -> None:
        slot = self._make_slot()
        j = slot.to_json()
        parsed = json.loads(j)
        assert parsed["device_id"] == "dev_ser_001"

    def test_to_json_round_trips_to_dict(self) -> None:
        slot = self._make_slot()
        assert json.loads(slot.to_json()) == slot.to_dict()


# ---------------------------------------------------------------------------
# Section 4 — evaluate_canonical_dispatch_slot — happy path
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _AUTHORITY_AVAILABLE, reason="canonical_dispatch_slot_authority unavailable")
class TestSlotHappyPath:
    """evaluate_canonical_dispatch_slot returns SLOT_APPROVED when all gates pass."""

    def _patch_all_gates_pass(self, device_id: str):
        """Context manager that patches all sub-checks to pass."""
        from core.canonical_dispatch_slot_authority import (
            _eval_base_readiness_gate,
            _eval_continuity_legality,
            _eval_delegated_handoff_acceptability,
            _eval_execution_mode_eligibility,
            _eval_occupancy,
            _eval_policy_allowance,
        )
        ready = _make_ready_gate_result(device_id)
        patches = [
            patch(
                "core.canonical_dispatch_slot_authority._eval_base_readiness_gate",
                return_value=ready,
            ),
            patch(
                "core.canonical_dispatch_slot_authority._eval_continuity_legality",
                return_value=("allow", []),
            ),
            patch(
                "core.canonical_dispatch_slot_authority._eval_execution_mode_eligibility",
                return_value=(True, []),
            ),
            patch(
                "core.canonical_dispatch_slot_authority._eval_occupancy",
                return_value=(True, []),
            ),
            patch(
                "core.canonical_dispatch_slot_authority._eval_policy_allowance",
                return_value=(True, []),
            ),
            patch(
                "core.canonical_dispatch_slot_authority._eval_delegated_handoff_acceptability",
                return_value=(True, []),
            ),
        ]
        return patches

    def test_returns_slot_approved_when_all_pass(self) -> None:
        did = _device_id()
        ready = _make_ready_gate_result(did)
        with (
            patch("core.canonical_dispatch_slot_authority._eval_base_readiness_gate", return_value=ready),
            patch("core.canonical_dispatch_slot_authority._eval_continuity_legality", return_value=("allow", [])),
            patch("core.canonical_dispatch_slot_authority._eval_execution_mode_eligibility", return_value=(True, [])),
            patch("core.canonical_dispatch_slot_authority._eval_occupancy", return_value=(True, [])),
            patch("core.canonical_dispatch_slot_authority._eval_policy_allowance", return_value=(True, [])),
            patch("core.canonical_dispatch_slot_authority._eval_delegated_handoff_acceptability", return_value=(True, [])),
        ):
            slot = evaluate_canonical_dispatch_slot(did, "cross_device")

        assert slot.slot_approved is True
        assert slot.status == CanonicalDispatchSlotStatus.SLOT_APPROVED.value

    def test_slot_approved_has_empty_blocking_dimension(self) -> None:
        did = _device_id()
        ready = _make_ready_gate_result(did)
        with (
            patch("core.canonical_dispatch_slot_authority._eval_base_readiness_gate", return_value=ready),
            patch("core.canonical_dispatch_slot_authority._eval_continuity_legality", return_value=("allow", [])),
            patch("core.canonical_dispatch_slot_authority._eval_execution_mode_eligibility", return_value=(True, [])),
            patch("core.canonical_dispatch_slot_authority._eval_occupancy", return_value=(True, [])),
            patch("core.canonical_dispatch_slot_authority._eval_policy_allowance", return_value=(True, [])),
            patch("core.canonical_dispatch_slot_authority._eval_delegated_handoff_acceptability", return_value=(True, [])),
        ):
            slot = evaluate_canonical_dispatch_slot(did, "cross_device")

        assert slot.blocking_dimension == ""

    def test_slot_approved_dimension_results_includes_core_dimensions(self) -> None:
        did = _device_id()
        ready = _make_ready_gate_result(did)
        with (
            patch("core.canonical_dispatch_slot_authority._eval_base_readiness_gate", return_value=ready),
            patch("core.canonical_dispatch_slot_authority._eval_continuity_legality", return_value=("allow", [])),
            patch("core.canonical_dispatch_slot_authority._eval_execution_mode_eligibility", return_value=(True, [])),
            patch("core.canonical_dispatch_slot_authority._eval_occupancy", return_value=(True, [])),
            patch("core.canonical_dispatch_slot_authority._eval_policy_allowance", return_value=(True, [])),
            patch("core.canonical_dispatch_slot_authority._eval_delegated_handoff_acceptability", return_value=(True, [])),
        ):
            slot = evaluate_canonical_dispatch_slot(did, "cross_device")

        expected_dims = {
            "transport_readiness", "registration_validity", "attachment_validity",
            "capability_fit", "cross_device_reachability",
            "continuity_legality", "execution_mode_eligibility",
            "occupancy", "policy_allowance",
        }
        for dim in expected_dims:
            assert dim in slot.dimension_results, f"Missing dimension: {dim!r}"


# ---------------------------------------------------------------------------
# Section 5 — base gate blocking
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _AUTHORITY_AVAILABLE, reason="canonical_dispatch_slot_authority unavailable")
class TestBaseGateBlocking:
    """Base gate failures produce the right slot status."""

    def test_not_registered_produces_slot_not_registered(self) -> None:
        did = _device_id()
        blocked = _make_blocked_gate_result(did, "not_registered", "not in UDM")
        with patch("core.canonical_dispatch_slot_authority._eval_base_readiness_gate", return_value=blocked):
            slot = evaluate_canonical_dispatch_slot(did, "cross_device")
        assert slot.slot_approved is False
        assert slot.status == CanonicalDispatchSlotStatus.SLOT_NOT_REGISTERED.value

    def test_transport_blocked_produces_slot_blocked_transport(self) -> None:
        did = _device_id()
        blocked = _make_blocked_gate_result(did, "blocked_transport", "WebSocket closed")
        with patch("core.canonical_dispatch_slot_authority._eval_base_readiness_gate", return_value=blocked):
            slot = evaluate_canonical_dispatch_slot(did, "single_device_remote")
        assert slot.slot_approved is False
        assert slot.status == CanonicalDispatchSlotStatus.SLOT_BLOCKED_TRANSPORT.value

    def test_stale_attachment_produces_slot_blocked_attachment(self) -> None:
        did = _device_id()
        blocked = _make_blocked_gate_result(
            did, "blocked_stale_attachment", "session replaced"
        )
        with patch("core.canonical_dispatch_slot_authority._eval_base_readiness_gate", return_value=blocked):
            slot = evaluate_canonical_dispatch_slot(did, "delegated_runtime")
        assert slot.slot_approved is False
        assert slot.status == CanonicalDispatchSlotStatus.SLOT_BLOCKED_ATTACHMENT.value

    def test_registration_gap_produces_slot_blocked_registration(self) -> None:
        did = _device_id()
        blocked = _make_blocked_gate_result(
            did, "blocked_registration_gap", "UDM write failed"
        )
        blocked.registration_gaps = ["udm_write_failed"]
        with patch("core.canonical_dispatch_slot_authority._eval_base_readiness_gate", return_value=blocked):
            slot = evaluate_canonical_dispatch_slot(did, "single_device_remote")
        assert slot.slot_approved is False
        assert slot.status == CanonicalDispatchSlotStatus.SLOT_BLOCKED_REGISTRATION.value


# ---------------------------------------------------------------------------
# Section 6 — new dimension blocking
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _AUTHORITY_AVAILABLE, reason="canonical_dispatch_slot_authority unavailable")
class TestNewDimensionBlocking:
    """Blocking in new dimensions (4, 6, 7, 8, 10) produces correct slot status."""

    def _ready_gate(self, device_id: str) -> Any:
        return _make_ready_gate_result(device_id)

    def test_continuity_reject_produces_slot_blocked_continuity_legality(self) -> None:
        did = _device_id()
        ready = self._ready_gate(did)
        with (
            patch("core.canonical_dispatch_slot_authority._eval_base_readiness_gate", return_value=ready),
            patch("core.canonical_dispatch_slot_authority._eval_continuity_legality",
                  return_value=("reject", ["stale runtime identity"])),
        ):
            slot = evaluate_canonical_dispatch_slot(did, "cross_device")
        assert slot.slot_approved is False
        assert slot.status == CanonicalDispatchSlotStatus.SLOT_BLOCKED_CONTINUITY_LEGALITY.value
        assert slot.blocking_dimension == "continuity_legality"

    def test_hard_reject_continuity_produces_slot_blocked_continuity_legality(self) -> None:
        did = _device_id()
        ready = self._ready_gate(did)
        with (
            patch("core.canonical_dispatch_slot_authority._eval_base_readiness_gate", return_value=ready),
            patch("core.canonical_dispatch_slot_authority._eval_continuity_legality",
                  return_value=("hard_reject", ["revoked session"])),
        ):
            slot = evaluate_canonical_dispatch_slot(did, "delegated_runtime")
        assert slot.slot_approved is False
        assert slot.status == CanonicalDispatchSlotStatus.SLOT_BLOCKED_CONTINUITY_LEGALITY.value

    def test_mode_ineligible_produces_slot_blocked_execution_mode_ineligible(self) -> None:
        did = _device_id()
        ready = self._ready_gate(did)
        with (
            patch("core.canonical_dispatch_slot_authority._eval_base_readiness_gate", return_value=ready),
            patch("core.canonical_dispatch_slot_authority._eval_continuity_legality",
                  return_value=("allow", [])),
            patch("core.canonical_dispatch_slot_authority._eval_execution_mode_eligibility",
                  return_value=(False, ["device does not support concurrent execution"])),
        ):
            slot = evaluate_canonical_dispatch_slot(did, "parallel_fanout")
        assert slot.slot_approved is False
        assert slot.status == CanonicalDispatchSlotStatus.SLOT_BLOCKED_EXECUTION_MODE_INELIGIBLE.value
        assert slot.blocking_dimension == "execution_mode_eligibility"

    def test_occupied_produces_slot_blocked_occupancy(self) -> None:
        did = _device_id()
        ready = self._ready_gate(did)
        with (
            patch("core.canonical_dispatch_slot_authority._eval_base_readiness_gate", return_value=ready),
            patch("core.canonical_dispatch_slot_authority._eval_continuity_legality",
                  return_value=("allow", [])),
            patch("core.canonical_dispatch_slot_authority._eval_execution_mode_eligibility",
                  return_value=(True, [])),
            patch("core.canonical_dispatch_slot_authority._eval_occupancy",
                  return_value=(False, ["device at task capacity"])),
        ):
            slot = evaluate_canonical_dispatch_slot(did, "cross_device")
        assert slot.slot_approved is False
        assert slot.status == CanonicalDispatchSlotStatus.SLOT_BLOCKED_OCCUPANCY.value
        assert slot.blocking_dimension == "occupancy"

    def test_policy_rejected_produces_slot_blocked_policy(self) -> None:
        did = _device_id()
        ready = self._ready_gate(did)
        with (
            patch("core.canonical_dispatch_slot_authority._eval_base_readiness_gate", return_value=ready),
            patch("core.canonical_dispatch_slot_authority._eval_continuity_legality",
                  return_value=("allow", [])),
            patch("core.canonical_dispatch_slot_authority._eval_execution_mode_eligibility",
                  return_value=(True, [])),
            patch("core.canonical_dispatch_slot_authority._eval_occupancy",
                  return_value=(True, [])),
            patch("core.canonical_dispatch_slot_authority._eval_policy_allowance",
                  return_value=(False, ["device is in maintenance mode"])),
        ):
            slot = evaluate_canonical_dispatch_slot(did, "single_device_remote")
        assert slot.slot_approved is False
        assert slot.status == CanonicalDispatchSlotStatus.SLOT_BLOCKED_POLICY.value
        assert slot.blocking_dimension == "policy_allowance"

    def test_delegated_rejected_produces_slot_blocked_delegated_handoff(self) -> None:
        did = _device_id()
        ready = self._ready_gate(did)
        with (
            patch("core.canonical_dispatch_slot_authority._eval_base_readiness_gate", return_value=ready),
            patch("core.canonical_dispatch_slot_authority._eval_continuity_legality",
                  return_value=("allow", [])),
            patch("core.canonical_dispatch_slot_authority._eval_execution_mode_eligibility",
                  return_value=(True, [])),
            patch("core.canonical_dispatch_slot_authority._eval_occupancy",
                  return_value=(True, [])),
            patch("core.canonical_dispatch_slot_authority._eval_policy_allowance",
                  return_value=(True, [])),
            patch("core.canonical_dispatch_slot_authority._eval_delegated_handoff_acceptability",
                  return_value=(False, ["DelegatedFlowAcceptanceGate: rejected"])),
        ):
            slot = evaluate_canonical_dispatch_slot(did, "delegated_runtime")
        assert slot.slot_approved is False
        assert slot.status == CanonicalDispatchSlotStatus.SLOT_BLOCKED_DELEGATED_HANDOFF.value
        assert slot.blocking_dimension == "delegated_handoff_acceptability"


# ---------------------------------------------------------------------------
# Section 7 — get_canonical_dispatch_slots multi-device
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _AUTHORITY_AVAILABLE, reason="canonical_dispatch_slot_authority unavailable")
class TestGetCanonicalDispatchSlots:
    """get_canonical_dispatch_slots correctly partitions approved vs blocked."""

    def _patch_slot(self, approved: bool, device_id: str):
        """Return a slot that is either approved or blocked."""
        if approved:
            return CanonicalDispatchSlot(
                device_id=device_id,
                execution_mode="parallel_fanout",
                slot_approved=True,
                status=CanonicalDispatchSlotStatus.SLOT_APPROVED.value,
                reason="mock: approved",
                registered=True,
                transport_alive=True,
                attachment_state="active",
            )
        else:
            return CanonicalDispatchSlot(
                device_id=device_id,
                execution_mode="parallel_fanout",
                slot_approved=False,
                status=CanonicalDispatchSlotStatus.SLOT_BLOCKED_TRANSPORT.value,
                reason="mock: transport down",
                registered=True,
                transport_alive=False,
            )

    def test_all_approved_can_proceed_true(self) -> None:
        did_a, did_b = _device_id(), _device_id()
        slot_a = self._patch_slot(True, did_a)
        slot_b = self._patch_slot(True, did_b)
        with patch(
            "core.canonical_dispatch_slot_authority.evaluate_canonical_dispatch_slot",
            side_effect=[slot_a, slot_b],
        ):
            result = get_canonical_dispatch_slots([did_a, did_b], "parallel_fanout")
        assert result.can_proceed is True
        assert result.approved_device_ids == [did_a, did_b]
        assert result.blocked_device_ids == []

    def test_mixed_can_proceed_true_with_partial_approval(self) -> None:
        did_a, did_b = _device_id(), _device_id()
        slot_a = self._patch_slot(True, did_a)
        slot_b = self._patch_slot(False, did_b)
        with patch(
            "core.canonical_dispatch_slot_authority.evaluate_canonical_dispatch_slot",
            side_effect=[slot_a, slot_b],
        ):
            result = get_canonical_dispatch_slots([did_a, did_b], "parallel_fanout")
        assert result.can_proceed is True
        assert did_a in result.approved_device_ids
        assert did_b in result.blocked_device_ids

    def test_all_blocked_can_proceed_false(self) -> None:
        did_a, did_b = _device_id(), _device_id()
        slot_a = self._patch_slot(False, did_a)
        slot_b = self._patch_slot(False, did_b)
        with patch(
            "core.canonical_dispatch_slot_authority.evaluate_canonical_dispatch_slot",
            side_effect=[slot_a, slot_b],
        ):
            result = get_canonical_dispatch_slots([did_a, did_b], "parallel_fanout")
        assert result.can_proceed is False
        assert len(result.approved_slots) == 0
        assert len(result.blocked_slots) == 2

    def test_empty_device_list_can_proceed_false(self) -> None:
        result = get_canonical_dispatch_slots([], "cross_device")
        assert result.can_proceed is False
        assert "empty" in result.block_reason.lower() or "no candidate" in result.block_reason.lower()

    def test_approved_slots_not_raw_devices(self) -> None:
        """Fan-out must select slots, not raw devices."""
        did_a = _device_id()
        slot_a = self._patch_slot(True, did_a)
        with patch(
            "core.canonical_dispatch_slot_authority.evaluate_canonical_dispatch_slot",
            return_value=slot_a,
        ):
            result = get_canonical_dispatch_slots([did_a], "parallel_fanout")
        # The result contains CanonicalDispatchSlot objects, not raw device IDs
        assert all(isinstance(s, CanonicalDispatchSlot) for s in result.approved_slots)


# ---------------------------------------------------------------------------
# Section 8 — Execution modes all use the same authority
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _AUTHORITY_AVAILABLE, reason="canonical_dispatch_slot_authority unavailable")
class TestExecutionModesCoverageByAuthority:
    """All execution modes go through evaluate_canonical_dispatch_slot."""

    def _make_slot(self, did: str, mode: str, approved: bool = True) -> CanonicalDispatchSlot:
        return CanonicalDispatchSlot(
            device_id=did,
            execution_mode=mode,
            slot_approved=approved,
            status=(
                CanonicalDispatchSlotStatus.SLOT_APPROVED.value
                if approved
                else CanonicalDispatchSlotStatus.SLOT_BLOCKED_TRANSPORT.value
            ),
            reason="mock",
        )

    @pytest.mark.parametrize("mode", [
        "parallel_fanout",
        "delegated_runtime",
        "wake_routed",
        "handoff",
        "hybrid",
        "cross_device",
        "single_device_remote",
        "local",
        "takeover",
    ])
    def test_mode_calls_evaluate_canonical_slot(self, mode: str) -> None:
        """evaluate_canonical_dispatch_slot is the call site for every mode."""
        did = _device_id()
        mock_slot = self._make_slot(did, mode)
        with patch(
            "core.canonical_dispatch_slot_authority.evaluate_canonical_dispatch_slot",
            return_value=mock_slot,
        ) as mock_eval:
            result = get_canonical_dispatch_slots([did], mode)
        # evaluate_canonical_dispatch_slot was called once for the single device
        mock_eval.assert_called_once_with(
            did,
            mode,
            required_capabilities=[],
            session_id=None,
            runtime_attachment_session_id=None,
            task_id=None,
            continuity_context={},
        )

    def test_parallel_fanout_collects_all_approved_slots(self) -> None:
        """Fan-out collects multiple approved slots, not raw devices."""
        dids = [_device_id() for _ in range(3)]
        slots = [self._make_slot(d, "parallel_fanout") for d in dids]
        with patch(
            "core.canonical_dispatch_slot_authority.evaluate_canonical_dispatch_slot",
            side_effect=slots,
        ):
            result = get_canonical_dispatch_slots(dids, "parallel_fanout")
        assert result.can_proceed is True
        assert len(result.approved_slots) == 3

    def test_wake_routed_mode_does_not_bypass_authority(self) -> None:
        """Wake-routed dispatch goes through evaluate_canonical_dispatch_slot."""
        did = _device_id()
        slot = self._make_slot(did, "wake_routed")
        with patch(
            "core.canonical_dispatch_slot_authority.evaluate_canonical_dispatch_slot",
            return_value=slot,
        ) as mock_eval:
            get_canonical_dispatch_slots([did], "wake_routed")
        mock_eval.assert_called_once()

    def test_delegated_runtime_evaluates_handoff_dimension(self) -> None:
        """delegated_runtime mode triggers delegated_handoff_acceptability check."""
        did = _device_id()
        ready = _make_ready_gate_result(did)
        with (
            patch("core.canonical_dispatch_slot_authority._eval_base_readiness_gate", return_value=ready),
            patch("core.canonical_dispatch_slot_authority._eval_continuity_legality",
                  return_value=("allow", [])),
            patch("core.canonical_dispatch_slot_authority._eval_execution_mode_eligibility",
                  return_value=(True, [])),
            patch("core.canonical_dispatch_slot_authority._eval_occupancy",
                  return_value=(True, [])),
            patch("core.canonical_dispatch_slot_authority._eval_policy_allowance",
                  return_value=(True, [])),
            patch(
                "core.canonical_dispatch_slot_authority._eval_delegated_handoff_acceptability",
                return_value=(True, []),
            ) as mock_dh,
        ):
            evaluate_canonical_dispatch_slot(did, "delegated_runtime")
        mock_dh.assert_called_once()


# ---------------------------------------------------------------------------
# Section 9 — Error safety
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _AUTHORITY_AVAILABLE, reason="canonical_dispatch_slot_authority unavailable")
class TestErrorSafety:
    """Authority functions never raise; they return safe error results."""

    def test_evaluate_slot_does_not_raise_with_empty_device_id(self) -> None:
        slot = evaluate_canonical_dispatch_slot("", "cross_device")
        # Should return some blocking result without raising
        assert isinstance(slot, CanonicalDispatchSlot)
        assert slot.slot_approved is False

    def test_evaluate_slot_does_not_raise_with_unknown_mode(self) -> None:
        slot = evaluate_canonical_dispatch_slot("some_device", "totally_unknown_mode_xyz")
        assert isinstance(slot, CanonicalDispatchSlot)

    def test_get_slots_does_not_raise_with_empty_list(self) -> None:
        result = get_canonical_dispatch_slots([], "parallel_fanout")
        assert isinstance(result, CanonicalDispatchSlotsResult)
        assert result.can_proceed is False

    def test_evaluate_slot_never_raises_on_internal_error(self) -> None:
        """Even if all sub-checks raise, evaluate_canonical_dispatch_slot must return safely."""
        with patch(
            "core.canonical_dispatch_slot_authority._evaluate_slot_impl",
            side_effect=RuntimeError("simulated internal failure"),
        ):
            slot = evaluate_canonical_dispatch_slot("dev_err", "local")
        assert slot.slot_approved is False
        assert slot.status == CanonicalDispatchSlotStatus.SLOT_AUTHORITY_ERROR.value


# ---------------------------------------------------------------------------
# Section 10 — DispatchReadinessStatus new values
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _GATE_AVAILABLE, reason="unified_dispatch_readiness_gate unavailable")
class TestDispatchReadinessStatusNewValues:
    """New DispatchReadinessStatus values for PR-V3 are present."""

    def test_blocked_continuity_legality_present(self) -> None:
        assert hasattr(DispatchReadinessStatus, "BLOCKED_CONTINUITY_LEGALITY")
        assert DispatchReadinessStatus.BLOCKED_CONTINUITY_LEGALITY.value == "blocked_continuity_legality"

    def test_blocked_execution_mode_ineligible_present(self) -> None:
        assert hasattr(DispatchReadinessStatus, "BLOCKED_EXECUTION_MODE_INELIGIBLE")
        assert DispatchReadinessStatus.BLOCKED_EXECUTION_MODE_INELIGIBLE.value == "blocked_execution_mode_ineligible"

    def test_blocked_occupancy_present(self) -> None:
        assert hasattr(DispatchReadinessStatus, "BLOCKED_OCCUPANCY")
        assert DispatchReadinessStatus.BLOCKED_OCCUPANCY.value == "blocked_occupancy"

    def test_blocked_policy_present(self) -> None:
        assert hasattr(DispatchReadinessStatus, "BLOCKED_POLICY")
        assert DispatchReadinessStatus.BLOCKED_POLICY.value == "blocked_policy"

    def test_original_values_still_present(self) -> None:
        """Ensure backward compatibility — original statuses must still exist."""
        for name in (
            "DISPATCH_READY", "REGISTERED_NOT_READY", "BLOCKED_REGISTRATION_GAP",
            "BLOCKED_STALE_ATTACHMENT", "BLOCKED_TRANSPORT", "BLOCKED_CAPABILITY",
            "BLOCKED_SESSION_VALIDITY", "BLOCKED_CROSS_DEVICE_ELIGIBILITY",
            "NOT_REGISTERED", "GATE_ERROR",
        ):
            assert hasattr(DispatchReadinessStatus, name), (
                f"Original DispatchReadinessStatus.{name} is missing"
            )
