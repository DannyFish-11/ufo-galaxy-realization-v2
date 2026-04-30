"""tests/test_pr_v4_orchestration_spine_unification.py
=========================================================
Test suite for PR-V4: Collapse advanced execution modes into a single
orchestration spine.

Coverage
--------
1. V4 sentinel importability
   - ORCHESTRATION_SPINE_V4_CONSUMES_CANONICAL_SLOT_POLICY is a non-empty string.
   - ORCHESTRATION_SPINE_LIFECYCLE_STAGE_IS_UNIFIED_POLICY is a non-empty string.
   - ORCHESTRATION_SPINE_AUDIT_RECORD_IS_CANONICAL_POLICY is a non-empty string.
   - All sentinels are importable from core.unified_orchestration_spine.

2. OrchestrationLifecycleStage enum
   - All expected stage values are present.
   - Stage values are string-valued.
   - PRE_EVALUATION, SLOT_EVALUATION, DISPATCH_EVALUATED are present.
   - DISPATCHING, AWAITING_RESULT, PARTIAL_FAILURE, COMPLETE, ABORTED present.

3. DeviceOrchestrationSlot — new canonical fields
   - slot_status field present and defaults to empty string.
   - blocking_dimension field present and defaults to empty string.
   - dimension_results field present and defaults to empty dict.
   - to_dict() includes slot_status, blocking_dimension, dimension_results.

4. OrchestrationDecision — new V4 fields
   - lifecycle_stage field present and defaults to DISPATCH_EVALUATED.
   - audit_record field present and defaults to empty dict.
   - to_dict() includes lifecycle_stage and audit_record.

5. evaluate_orchestration_request — canonical slot authority consumed
   - Spine now calls canonical dispatch-slot authority, not readiness gate.
   - decision.lifecycle_stage equals DISPATCH_EVALUATED when can_proceed.
   - decision.lifecycle_stage equals ABORTED when all slots blocked.
   - decision.audit_record is populated with orchestration_id, execution_mode,
     lifecycle_stage, ready_device_count, blocked_device_count.
   - Empty target_device_ids → ABORTED lifecycle stage.

6. All execution modes route through canonical slot authority
   - LOCAL mode populates slot_status on blocked slots.
   - PARALLEL_FANOUT mode populates slot_status on all slots.
   - HANDOFF mode populates slot_status on all slots.
   - WAKE_ROUTED mode populates slot_status on all slots.
   - DELEGATED_RUNTIME mode populates slot_status on all slots.
   - HYBRID mode populates slot_status on all slots.
   - CROSS_DEVICE mode populates slot_status on all slots.

7. Backward compatibility — readiness_status mapping
   - Slot with slot_status=slot_blocked_registration maps to
     readiness_status=blocked_registration_gap.
   - Slot with slot_status=slot_blocked_transport maps to
     readiness_status=blocked_transport.
   - Slot with slot_status=slot_not_registered maps to
     readiness_status=not_registered.
   - Slot with slot_status=slot_approved maps to
     readiness_status=dispatch_ready.

8. audit_record canonical fields
   - audit_record contains execution_mode key.
   - audit_record contains lifecycle_stage key.
   - audit_record contains ready_device_count key.
   - audit_record contains blocked_device_count key.
   - audit_record contains completion_contract key.
   - audit_record contains orchestration_id key.

9. Serialisation
   - OrchestrationDecision.to_dict() includes lifecycle_stage key.
   - OrchestrationDecision.to_dict() includes audit_record key.
   - OrchestrationDecision.to_json() is valid JSON.
   - DeviceOrchestrationSlot.to_dict() includes slot_status key.
   - DeviceOrchestrationSlot.to_dict() includes blocking_dimension key.
   - DeviceOrchestrationSlot.to_dict() includes dimension_results key.

10. Error safety
    - evaluate_orchestration_request never raises with any execution mode.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Availability guards
# ---------------------------------------------------------------------------

try:
    from core.unified_orchestration_spine import (
        ALL_EXECUTION_MODES_MUST_USE_SPINE_POLICY,
        CANONICAL_DISPATCH_SLOT_AUTHORITY_IS_SPINE_CONSUMER_POLICY,
        CompletionContract,
        DeviceOrchestrationSlot,
        ExecutionMode,
        ORCHESTRATION_SPINE_AUDIT_RECORD_IS_CANONICAL_POLICY,
        ORCHESTRATION_SPINE_LIFECYCLE_STAGE_IS_UNIFIED_POLICY,
        ORCHESTRATION_SPINE_V4_CONSUMES_CANONICAL_SLOT_POLICY,
        OrchestrationDecision,
        OrchestrationLifecycleStage,
        OrchestrationRequest,
        PARALLEL_FANOUT_MUST_USE_SPINE_POLICY,
        SPINE_COMPLETION_CONTRACT_IS_UNIFIED_POLICY,
        UNIFIED_ORCHESTRATION_SPINE_AUTHORITY,
        WAKE_HANDOFF_DELEGATED_MUST_USE_SPINE_POLICY,
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
        get_canonical_dispatch_slots,
    )
    _AUTHORITY_AVAILABLE = True
except ImportError:
    _AUTHORITY_AVAILABLE = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _device_id() -> str:
    return f"dev_{uuid.uuid4().hex[:8]}"


def _make_approved_canonical_slot(device_id: str, execution_mode: str = "single_device_remote") -> "CanonicalDispatchSlot":
    """Build a fully approved CanonicalDispatchSlot for patching."""
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


def _make_blocked_canonical_slot(
    device_id: str,
    execution_mode: str = "single_device_remote",
    status: str = "slot_blocked_registration",
    blocking_dimension: str = "registration_validity",
) -> "CanonicalDispatchSlot":
    """Build a blocked CanonicalDispatchSlot for patching."""
    return CanonicalDispatchSlot(
        device_id=device_id,
        execution_mode=execution_mode,
        slot_approved=False,
        status=status,
        reason=f"Blocked by {blocking_dimension}",
        dimension_results={"transport_readiness": True, "registration_validity": False},
        blocking_dimension=blocking_dimension,
        registered=True,
        transport_alive=True,
        attachment_state="active",
        registration_gaps=["udm_write"],
    )


def _make_slots_result(
    execution_mode: str,
    approved: List["CanonicalDispatchSlot"],
    blocked: List["CanonicalDispatchSlot"],
) -> "CanonicalDispatchSlotsResult":
    return CanonicalDispatchSlotsResult(
        execution_mode=execution_mode,
        approved_slots=approved,
        blocked_slots=blocked,
        can_proceed=len(approved) > 0,
        block_reason="" if approved else "All devices blocked.",
        authority_notes=[],
    )


# ---------------------------------------------------------------------------
# Section 1 — V4 sentinel importability
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _SPINE_AVAILABLE, reason="spine unavailable")
class TestV4SentinelImportability:
    """V4 policy sentinels are importable and non-empty."""

    def test_v4_consumes_canonical_slot_policy_non_empty(self) -> None:
        assert isinstance(ORCHESTRATION_SPINE_V4_CONSUMES_CANONICAL_SLOT_POLICY, str)
        assert len(ORCHESTRATION_SPINE_V4_CONSUMES_CANONICAL_SLOT_POLICY) > 0

    def test_v4_lifecycle_stage_policy_non_empty(self) -> None:
        assert isinstance(ORCHESTRATION_SPINE_LIFECYCLE_STAGE_IS_UNIFIED_POLICY, str)
        assert len(ORCHESTRATION_SPINE_LIFECYCLE_STAGE_IS_UNIFIED_POLICY) > 0

    def test_v4_audit_record_policy_non_empty(self) -> None:
        assert isinstance(ORCHESTRATION_SPINE_AUDIT_RECORD_IS_CANONICAL_POLICY, str)
        assert len(ORCHESTRATION_SPINE_AUDIT_RECORD_IS_CANONICAL_POLICY) > 0

    def test_v4_policy_mentions_canonical_slot_authority(self) -> None:
        assert "canonical" in ORCHESTRATION_SPINE_V4_CONSUMES_CANONICAL_SLOT_POLICY.lower()

    def test_v4_policy_mentions_all_execution_modes(self) -> None:
        policy = ORCHESTRATION_SPINE_V4_CONSUMES_CANONICAL_SLOT_POLICY
        assert "handoff" in policy.lower()
        assert "delegated" in policy.lower()
        assert "wake" in policy.lower()
        assert "parallel" in policy.lower()

    def test_existing_sentinels_still_importable(self) -> None:
        assert len(UNIFIED_ORCHESTRATION_SPINE_AUTHORITY) > 0
        assert len(ALL_EXECUTION_MODES_MUST_USE_SPINE_POLICY) > 0
        assert len(PARALLEL_FANOUT_MUST_USE_SPINE_POLICY) > 0
        assert len(WAKE_HANDOFF_DELEGATED_MUST_USE_SPINE_POLICY) > 0
        assert len(SPINE_COMPLETION_CONTRACT_IS_UNIFIED_POLICY) > 0
        assert len(CANONICAL_DISPATCH_SLOT_AUTHORITY_IS_SPINE_CONSUMER_POLICY) > 0

    def test_unified_authority_mentions_v4(self) -> None:
        assert "V4" in UNIFIED_ORCHESTRATION_SPINE_AUTHORITY or "v4" in UNIFIED_ORCHESTRATION_SPINE_AUTHORITY.lower()


# ---------------------------------------------------------------------------
# Section 2 — OrchestrationLifecycleStage enum
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _SPINE_AVAILABLE, reason="spine unavailable")
class TestOrchestrationLifecycleStageEnum:
    """OrchestrationLifecycleStage has all expected stages."""

    def test_pre_evaluation_present(self) -> None:
        assert OrchestrationLifecycleStage.PRE_EVALUATION.value == "pre_evaluation"

    def test_slot_evaluation_present(self) -> None:
        assert OrchestrationLifecycleStage.SLOT_EVALUATION.value == "slot_evaluation"

    def test_dispatch_evaluated_present(self) -> None:
        assert OrchestrationLifecycleStage.DISPATCH_EVALUATED.value == "dispatch_evaluated"

    def test_dispatching_present(self) -> None:
        assert OrchestrationLifecycleStage.DISPATCHING.value == "dispatching"

    def test_awaiting_result_present(self) -> None:
        assert OrchestrationLifecycleStage.AWAITING_RESULT.value == "awaiting_result"

    def test_partial_failure_present(self) -> None:
        assert OrchestrationLifecycleStage.PARTIAL_FAILURE.value == "partial_failure"

    def test_complete_present(self) -> None:
        assert OrchestrationLifecycleStage.COMPLETE.value == "complete"

    def test_aborted_present(self) -> None:
        assert OrchestrationLifecycleStage.ABORTED.value == "aborted"

    def test_all_values_are_strings(self) -> None:
        for stage in OrchestrationLifecycleStage:
            assert isinstance(stage.value, str)
            assert len(stage.value) > 0


# ---------------------------------------------------------------------------
# Section 3 — DeviceOrchestrationSlot new canonical fields
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _SPINE_AVAILABLE, reason="spine unavailable")
class TestDeviceOrchestrationSlotNewFields:
    """DeviceOrchestrationSlot carries canonical slot fields from V4."""

    def test_slot_status_field_defaults_empty(self) -> None:
        slot = DeviceOrchestrationSlot(device_id="dev_test")
        assert slot.slot_status == ""

    def test_blocking_dimension_field_defaults_empty(self) -> None:
        slot = DeviceOrchestrationSlot(device_id="dev_test")
        assert slot.blocking_dimension == ""

    def test_dimension_results_field_defaults_empty_dict(self) -> None:
        slot = DeviceOrchestrationSlot(device_id="dev_test")
        assert isinstance(slot.dimension_results, dict)
        assert len(slot.dimension_results) == 0

    def test_to_dict_includes_slot_status(self) -> None:
        slot = DeviceOrchestrationSlot(device_id="dev_x", slot_status="slot_approved")
        d = slot.to_dict()
        assert "slot_status" in d
        assert d["slot_status"] == "slot_approved"

    def test_to_dict_includes_blocking_dimension(self) -> None:
        slot = DeviceOrchestrationSlot(device_id="dev_x", blocking_dimension="occupancy")
        d = slot.to_dict()
        assert "blocking_dimension" in d
        assert d["blocking_dimension"] == "occupancy"

    def test_to_dict_includes_dimension_results(self) -> None:
        dims = {"transport_readiness": True, "occupancy": False}
        slot = DeviceOrchestrationSlot(device_id="dev_x", dimension_results=dims)
        d = slot.to_dict()
        assert "dimension_results" in d
        assert d["dimension_results"] == dims


# ---------------------------------------------------------------------------
# Section 4 — OrchestrationDecision new V4 fields
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _SPINE_AVAILABLE, reason="spine unavailable")
class TestOrchestrationDecisionNewFields:
    """OrchestrationDecision carries lifecycle_stage and audit_record."""

    def test_lifecycle_stage_defaults_to_dispatch_evaluated(self) -> None:
        dec = OrchestrationDecision()
        assert dec.lifecycle_stage == OrchestrationLifecycleStage.DISPATCH_EVALUATED.value

    def test_audit_record_defaults_to_empty_dict(self) -> None:
        dec = OrchestrationDecision()
        assert isinstance(dec.audit_record, dict)
        assert len(dec.audit_record) == 0

    def test_to_dict_includes_lifecycle_stage(self) -> None:
        dec = OrchestrationDecision(lifecycle_stage=OrchestrationLifecycleStage.DISPATCHING.value)
        d = dec.to_dict()
        assert "lifecycle_stage" in d
        assert d["lifecycle_stage"] == "dispatching"

    def test_to_dict_includes_audit_record(self) -> None:
        dec = OrchestrationDecision(audit_record={"foo": "bar"})
        d = dec.to_dict()
        assert "audit_record" in d
        assert d["audit_record"]["foo"] == "bar"


# ---------------------------------------------------------------------------
# Section 5 — evaluate_orchestration_request: lifecycle and audit
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (_SPINE_AVAILABLE and _AUTHORITY_AVAILABLE),
    reason="spine or authority unavailable",
)
class TestEvaluateOrchestrationRequestV4:
    """Spine sets lifecycle_stage and audit_record correctly."""

    def _patch_slots(self, approved, blocked, mode="single_device_remote"):
        """Return a context manager patching get_canonical_dispatch_slots."""
        result = _make_slots_result(mode, approved, blocked)
        return patch(
            "core.unified_orchestration_spine.get_canonical_dispatch_slots",
            return_value=result,
        )

    def test_lifecycle_stage_dispatch_evaluated_when_can_proceed(self) -> None:
        dev = _device_id()
        approved = [_make_approved_canonical_slot(dev)]
        with self._patch_slots(approved, []):
            req = OrchestrationRequest(
                execution_mode=ExecutionMode.SINGLE_DEVICE_REMOTE.value,
                target_device_ids=[dev],
            )
            decision = evaluate_orchestration_request(req)
        assert decision.lifecycle_stage == OrchestrationLifecycleStage.DISPATCH_EVALUATED.value

    def test_lifecycle_stage_aborted_when_all_blocked(self) -> None:
        dev = _device_id()
        blocked = [_make_blocked_canonical_slot(dev)]
        with self._patch_slots([], blocked):
            req = OrchestrationRequest(
                execution_mode=ExecutionMode.SINGLE_DEVICE_REMOTE.value,
                target_device_ids=[dev],
            )
            decision = evaluate_orchestration_request(req)
        assert decision.lifecycle_stage == OrchestrationLifecycleStage.ABORTED.value

    def test_lifecycle_stage_aborted_when_empty_target_list(self) -> None:
        req = OrchestrationRequest(
            execution_mode=ExecutionMode.LOCAL.value,
            target_device_ids=[],
        )
        decision = evaluate_orchestration_request(req)
        assert decision.lifecycle_stage == OrchestrationLifecycleStage.ABORTED.value

    def test_audit_record_populated_on_proceed(self) -> None:
        dev = _device_id()
        approved = [_make_approved_canonical_slot(dev)]
        with self._patch_slots(approved, []):
            req = OrchestrationRequest(
                execution_mode=ExecutionMode.SINGLE_DEVICE_REMOTE.value,
                target_device_ids=[dev],
            )
            decision = evaluate_orchestration_request(req)
        ar = decision.audit_record
        assert "orchestration_id" in ar
        assert "execution_mode" in ar
        assert "lifecycle_stage" in ar
        assert "ready_device_count" in ar
        assert "blocked_device_count" in ar
        assert "completion_contract" in ar

    def test_audit_record_ready_device_count_correct(self) -> None:
        dev1, dev2 = _device_id(), _device_id()
        approved = [
            _make_approved_canonical_slot(dev1),
            _make_approved_canonical_slot(dev2),
        ]
        with self._patch_slots(approved, [], mode="parallel_fanout"):
            req = OrchestrationRequest(
                execution_mode=ExecutionMode.PARALLEL_FANOUT.value,
                target_device_ids=[dev1, dev2],
            )
            decision = evaluate_orchestration_request(req)
        assert decision.audit_record["ready_device_count"] == 2
        assert decision.audit_record["blocked_device_count"] == 0

    def test_audit_record_blocked_device_count_correct(self) -> None:
        dev = _device_id()
        blocked = [_make_blocked_canonical_slot(dev)]
        with self._patch_slots([], blocked):
            req = OrchestrationRequest(
                execution_mode=ExecutionMode.SINGLE_DEVICE_REMOTE.value,
                target_device_ids=[dev],
            )
            decision = evaluate_orchestration_request(req)
        assert decision.audit_record["blocked_device_count"] == 1
        assert decision.audit_record["ready_device_count"] == 0

    def test_audit_record_orchestration_id_matches_decision(self) -> None:
        dev = _device_id()
        approved = [_make_approved_canonical_slot(dev)]
        with self._patch_slots(approved, []):
            req = OrchestrationRequest(
                execution_mode=ExecutionMode.LOCAL.value,
                target_device_ids=[dev],
            )
            decision = evaluate_orchestration_request(req)
        assert decision.audit_record["orchestration_id"] == decision.orchestration_id


# ---------------------------------------------------------------------------
# Section 6 — All execution modes route through canonical slot authority
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (_SPINE_AVAILABLE and _AUTHORITY_AVAILABLE),
    reason="spine or authority unavailable",
)
class TestAllModesUseCanonicalSlotAuthority:
    """Every execution mode populates slot_status from the canonical authority."""

    def _run_mode(self, mode: str) -> "OrchestrationDecision":
        dev = _device_id()
        blocked = [_make_blocked_canonical_slot(dev, execution_mode=mode)]
        result = _make_slots_result(mode, [], blocked)
        with patch(
            "core.unified_orchestration_spine.get_canonical_dispatch_slots",
            return_value=result,
        ):
            req = OrchestrationRequest(
                execution_mode=mode,
                target_device_ids=[dev],
            )
            return evaluate_orchestration_request(req)

    def test_local_mode_populates_slot_status(self) -> None:
        dec = self._run_mode(ExecutionMode.LOCAL.value)
        assert len(dec.blocked_slots) == 1
        assert dec.blocked_slots[0].slot_status != ""

    def test_parallel_fanout_mode_populates_slot_status(self) -> None:
        dec = self._run_mode(ExecutionMode.PARALLEL_FANOUT.value)
        assert len(dec.blocked_slots) == 1
        assert dec.blocked_slots[0].slot_status != ""

    def test_handoff_mode_populates_slot_status(self) -> None:
        dec = self._run_mode(ExecutionMode.HANDOFF.value)
        assert len(dec.blocked_slots) == 1
        assert dec.blocked_slots[0].slot_status != ""

    def test_wake_routed_mode_populates_slot_status(self) -> None:
        dec = self._run_mode(ExecutionMode.WAKE_ROUTED.value)
        assert len(dec.blocked_slots) == 1
        assert dec.blocked_slots[0].slot_status != ""

    def test_delegated_runtime_mode_populates_slot_status(self) -> None:
        dec = self._run_mode(ExecutionMode.DELEGATED_RUNTIME.value)
        assert len(dec.blocked_slots) == 1
        assert dec.blocked_slots[0].slot_status != ""

    def test_hybrid_mode_populates_slot_status(self) -> None:
        dec = self._run_mode(ExecutionMode.HYBRID.value)
        assert len(dec.blocked_slots) == 1
        assert dec.blocked_slots[0].slot_status != ""

    def test_cross_device_mode_populates_slot_status(self) -> None:
        dec = self._run_mode(ExecutionMode.CROSS_DEVICE.value)
        assert len(dec.blocked_slots) == 1
        assert dec.blocked_slots[0].slot_status != ""

    def test_takeover_mode_populates_slot_status(self) -> None:
        dec = self._run_mode(ExecutionMode.TAKEOVER.value)
        assert len(dec.blocked_slots) == 1
        assert dec.blocked_slots[0].slot_status != ""

    def test_single_device_remote_populates_slot_status(self) -> None:
        dec = self._run_mode(ExecutionMode.SINGLE_DEVICE_REMOTE.value)
        assert len(dec.blocked_slots) == 1
        assert dec.blocked_slots[0].slot_status != ""


# ---------------------------------------------------------------------------
# Section 7 — Backward compatibility: readiness_status mapping
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (_SPINE_AVAILABLE and _AUTHORITY_AVAILABLE),
    reason="spine or authority unavailable",
)
class TestReadinessStatusBackwardCompatMapping:
    """Canonical slot_status is mapped to legacy readiness_status values."""

    def _run_with_blocked_status(
        self, canonical_status: str, blocking_dim: str = "registration_validity"
    ) -> "DeviceOrchestrationSlot":
        dev = _device_id()
        blocked_slot = CanonicalDispatchSlot(
            device_id=dev,
            execution_mode="single_device_remote",
            slot_approved=False,
            status=canonical_status,
            reason="blocked",
            dimension_results={},
            blocking_dimension=blocking_dim,
        )
        result = _make_slots_result("single_device_remote", [], [blocked_slot])
        with patch(
            "core.unified_orchestration_spine.get_canonical_dispatch_slots",
            return_value=result,
        ):
            req = OrchestrationRequest(
                execution_mode=ExecutionMode.SINGLE_DEVICE_REMOTE.value,
                target_device_ids=[dev],
            )
            dec = evaluate_orchestration_request(req)
        assert len(dec.blocked_slots) == 1
        return dec.blocked_slots[0]

    def test_slot_blocked_registration_maps_to_blocked_registration_gap(self) -> None:
        slot = self._run_with_blocked_status("slot_blocked_registration")
        assert slot.readiness_status == "blocked_registration_gap"

    def test_slot_blocked_transport_maps_to_blocked_transport(self) -> None:
        slot = self._run_with_blocked_status(
            "slot_blocked_transport", "transport_readiness"
        )
        assert slot.readiness_status == "blocked_transport"

    def test_slot_not_registered_maps_to_not_registered(self) -> None:
        slot = self._run_with_blocked_status("slot_not_registered", "")
        assert slot.readiness_status == "not_registered"

    def test_slot_blocked_attachment_maps_to_blocked_stale_attachment(self) -> None:
        slot = self._run_with_blocked_status(
            "slot_blocked_attachment", "attachment_validity"
        )
        assert slot.readiness_status == "blocked_stale_attachment"

    def _run_with_approved_status(self) -> "DeviceOrchestrationSlot":
        dev = _device_id()
        approved_slot = _make_approved_canonical_slot(dev)
        result = _make_slots_result("single_device_remote", [approved_slot], [])
        with patch(
            "core.unified_orchestration_spine.get_canonical_dispatch_slots",
            return_value=result,
        ):
            req = OrchestrationRequest(
                execution_mode=ExecutionMode.SINGLE_DEVICE_REMOTE.value,
                target_device_ids=[dev],
            )
            dec = evaluate_orchestration_request(req)
        assert len(dec.ready_slots) == 1
        return dec.ready_slots[0]

    def test_slot_approved_maps_to_dispatch_ready(self) -> None:
        slot = self._run_with_approved_status()
        assert slot.readiness_status == "dispatch_ready"
        assert slot.slot_status == "slot_approved"


# ---------------------------------------------------------------------------
# Section 8 — audit_record canonical fields
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (_SPINE_AVAILABLE and _AUTHORITY_AVAILABLE),
    reason="spine or authority unavailable",
)
class TestAuditRecordCanonicalFields:
    """audit_record contains all canonical projection fields."""

    def _make_decision(self, mode: str = "single_device_remote") -> "OrchestrationDecision":
        dev = _device_id()
        approved = [_make_approved_canonical_slot(dev, execution_mode=mode)]
        result = _make_slots_result(mode, approved, [])
        with patch(
            "core.unified_orchestration_spine.get_canonical_dispatch_slots",
            return_value=result,
        ):
            req = OrchestrationRequest(
                execution_mode=mode,
                target_device_ids=[dev],
            )
            return evaluate_orchestration_request(req)

    def test_audit_record_execution_mode(self) -> None:
        dec = self._make_decision("parallel_fanout")
        assert dec.audit_record["execution_mode"] == "parallel_fanout"

    def test_audit_record_lifecycle_stage(self) -> None:
        dec = self._make_decision()
        assert dec.audit_record["lifecycle_stage"] == OrchestrationLifecycleStage.DISPATCH_EVALUATED.value

    def test_audit_record_completion_contract_is_dict(self) -> None:
        dec = self._make_decision()
        cc = dec.audit_record["completion_contract"]
        assert isinstance(cc, dict)
        assert "expected_result_count" in cc
        assert "partial_failure_policy" in cc
        assert "aggregation_mode" in cc

    def test_audit_record_orchestration_id_non_empty(self) -> None:
        dec = self._make_decision()
        assert isinstance(dec.audit_record["orchestration_id"], str)
        assert len(dec.audit_record["orchestration_id"]) > 0


# ---------------------------------------------------------------------------
# Section 9 — Serialisation
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _SPINE_AVAILABLE, reason="spine unavailable")
class TestSerialisation:
    """OrchestrationDecision and DeviceOrchestrationSlot serialise correctly."""

    def test_decision_to_dict_includes_lifecycle_stage(self) -> None:
        dec = OrchestrationDecision(
            lifecycle_stage=OrchestrationLifecycleStage.AWAITING_RESULT.value
        )
        d = dec.to_dict()
        assert "lifecycle_stage" in d
        assert d["lifecycle_stage"] == "awaiting_result"

    def test_decision_to_dict_includes_audit_record(self) -> None:
        dec = OrchestrationDecision(audit_record={"k": "v"})
        d = dec.to_dict()
        assert "audit_record" in d

    def test_decision_to_json_is_valid(self) -> None:
        dec = OrchestrationDecision(
            lifecycle_stage=OrchestrationLifecycleStage.COMPLETE.value,
            audit_record={"x": 1},
        )
        raw = dec.to_json()
        parsed = json.loads(raw)
        assert parsed["lifecycle_stage"] == "complete"
        assert parsed["audit_record"]["x"] == 1

    def test_slot_to_dict_includes_slot_status(self) -> None:
        slot = DeviceOrchestrationSlot(device_id="d", slot_status="slot_approved")
        d = slot.to_dict()
        assert "slot_status" in d

    def test_slot_to_dict_includes_blocking_dimension(self) -> None:
        slot = DeviceOrchestrationSlot(device_id="d", blocking_dimension="occupancy")
        d = slot.to_dict()
        assert "blocking_dimension" in d
        assert d["blocking_dimension"] == "occupancy"

    def test_slot_to_dict_includes_dimension_results(self) -> None:
        dims = {"transport_readiness": True}
        slot = DeviceOrchestrationSlot(device_id="d", dimension_results=dims)
        d = slot.to_dict()
        assert "dimension_results" in d
        assert d["dimension_results"] == dims


# ---------------------------------------------------------------------------
# Section 10 — Error safety
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _SPINE_AVAILABLE, reason="spine unavailable")
class TestErrorSafety:
    """evaluate_orchestration_request never raises."""

    def test_never_raises_with_local_mode(self) -> None:
        req = OrchestrationRequest(
            execution_mode=ExecutionMode.LOCAL.value,
            target_device_ids=[_device_id()],
        )
        result = evaluate_orchestration_request(req)
        assert isinstance(result, OrchestrationDecision)

    def test_never_raises_with_parallel_fanout(self) -> None:
        req = OrchestrationRequest(
            execution_mode=ExecutionMode.PARALLEL_FANOUT.value,
            target_device_ids=[_device_id(), _device_id()],
        )
        result = evaluate_orchestration_request(req)
        assert isinstance(result, OrchestrationDecision)

    def test_never_raises_with_handoff(self) -> None:
        req = OrchestrationRequest(
            execution_mode=ExecutionMode.HANDOFF.value,
            target_device_ids=[_device_id()],
        )
        result = evaluate_orchestration_request(req)
        assert isinstance(result, OrchestrationDecision)

    def test_never_raises_with_wake_routed(self) -> None:
        req = OrchestrationRequest(
            execution_mode=ExecutionMode.WAKE_ROUTED.value,
            target_device_ids=[_device_id()],
        )
        result = evaluate_orchestration_request(req)
        assert isinstance(result, OrchestrationDecision)

    def test_never_raises_with_delegated_runtime(self) -> None:
        req = OrchestrationRequest(
            execution_mode=ExecutionMode.DELEGATED_RUNTIME.value,
            target_device_ids=[_device_id()],
        )
        result = evaluate_orchestration_request(req)
        assert isinstance(result, OrchestrationDecision)

    def test_never_raises_with_hybrid(self) -> None:
        req = OrchestrationRequest(
            execution_mode=ExecutionMode.HYBRID.value,
            target_device_ids=[_device_id()],
        )
        result = evaluate_orchestration_request(req)
        assert isinstance(result, OrchestrationDecision)

    def test_never_raises_with_empty_targets(self) -> None:
        req = OrchestrationRequest(
            execution_mode=ExecutionMode.SINGLE_DEVICE_REMOTE.value,
            target_device_ids=[],
        )
        result = evaluate_orchestration_request(req)
        assert isinstance(result, OrchestrationDecision)
        assert not result.can_proceed
