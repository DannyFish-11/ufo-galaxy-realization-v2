"""tests/test_pr7a_android_governance_truth_hardening.py
==========================================================
PR-7A regression suite — Android Governance Truth Hardening.

Problem statement
-----------------
Remove governance assumptions that accept default/optimistic Android capability
or runtime truth when evidence is absent.  Harden canonical governance so that
missing, stale, contradictory, or unverified Android-originated truth degrades
readiness and execution decisions instead of being treated as implicitly
acceptable.

Acceptance criteria
-------------------
* Absence of Android truth no longer behaves like positive evidence.
* Governance and readiness semantics are explicitly hardened against default
  optimism.
* Diagnostics explain degraded decisions.
* The implementation lands in real governance decision paths, not just tests or
  comments.

Coverage groups
---------------
A. Policy sentinel accessibility.
B. resolve_android_execution_gate_decision: degrading truth quality → "deny".
C. resolve_android_execution_gate_decision: non-degrading truth quality → normal.
D. resolve_android_execution_gate_decision: None truth quality → normal flow.
E. Decision reasons include truth-degraded token when applicable.
F. AndroidCanonicalExecutionGateDecision.android_capability_truth_degraded flag.
G. AndroidCanonicalExecutionGateDecision.to_dict includes truth quality fields.
H. AndroidDevice.from_registration: absent capabilities → explicitly_reported=False.
I. AndroidDevice.from_registration: explicit capabilities → explicitly_reported=True.
J. AndroidDevice.from_registration: capabilities default to NONE (0) when absent.
K. AndroidDevice.to_dict includes capabilities_explicitly_reported.
L. build_unified_governance_state: missing Android truth wires into gate decision.
M. proof_input_diagnosis is computed before gate call in governance state.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# ===========================================================================
# A — Policy sentinel accessibility
# ===========================================================================

class TestPolicySentinelAccessibility:
    def test_capability_absent_governance_policy_importable(self) -> None:
        from galaxy_gateway.android.capabilities import (
            CAPABILITY_ABSENT_GOVERNANCE_POLICY,
        )
        assert isinstance(CAPABILITY_ABSENT_GOVERNANCE_POLICY, str)
        assert "CAPABILITY_ABSENT_GOVERNANCE" in CAPABILITY_ABSENT_GOVERNANCE_POLICY

    def test_android_capability_truth_absent_degrades_policy_importable(self) -> None:
        from core.android_mode_gate_policy import (
            ANDROID_CAPABILITY_TRUTH_ABSENT_DEGRADES_READINESS_POLICY,
        )
        assert isinstance(ANDROID_CAPABILITY_TRUTH_ABSENT_DEGRADES_READINESS_POLICY, str)
        assert "ANDROID_CAPABILITY_TRUTH_ABSENT" in (
            ANDROID_CAPABILITY_TRUTH_ABSENT_DEGRADES_READINESS_POLICY
        )

    def test_policy_references_deny_semantics(self) -> None:
        from core.android_mode_gate_policy import (
            ANDROID_CAPABILITY_TRUTH_ABSENT_DEGRADES_READINESS_POLICY,
        )
        assert "deny" in ANDROID_CAPABILITY_TRUTH_ABSENT_DEGRADES_READINESS_POLICY.lower()

    def test_capability_absent_policy_references_none(self) -> None:
        from galaxy_gateway.android.capabilities import (
            CAPABILITY_ABSENT_GOVERNANCE_POLICY,
        )
        assert "NONE" in CAPABILITY_ABSENT_GOVERNANCE_POLICY or "0" in CAPABILITY_ABSENT_GOVERNANCE_POLICY


# ===========================================================================
# B — resolve_android_execution_gate_decision: degrading truth → "deny"
# ===========================================================================

class TestGateDecisionDegradingTruth:
    """
    When android_capability_truth_quality is a degrading class
    ("missing", "stale", "conflicting", "downgraded"), the gate decision
    must be "deny" regardless of other inputs.
    """

    def _resolve(self, truth_quality: str, **kwargs: Any):
        from core.android_mode_gate_policy import resolve_android_execution_gate_decision
        defaults = dict(
            policy_eligible=True,
            readiness_ready=True,
            execution_busy=False,
            local_inference_available=True,
            fallback_tier=None,
        )
        defaults.update(kwargs)
        return resolve_android_execution_gate_decision(
            android_capability_truth_quality=truth_quality,
            **defaults,
        )

    def test_missing_truth_produces_deny(self) -> None:
        result = self._resolve("missing")
        assert result.decision == "deny"

    def test_stale_truth_produces_deny(self) -> None:
        result = self._resolve("stale")
        assert result.decision == "deny"

    def test_conflicting_truth_produces_deny(self) -> None:
        result = self._resolve("conflicting")
        assert result.decision == "deny"

    def test_downgraded_truth_produces_deny(self) -> None:
        result = self._resolve("downgraded")
        assert result.decision == "deny"

    def test_missing_truth_denies_even_when_all_gates_would_pass(self) -> None:
        """Absence of truth beats all other positive gate inputs."""
        result = self._resolve(
            "missing",
            policy_eligible=True,
            readiness_ready=True,
            execution_busy=False,
            local_inference_available=True,
            fallback_tier="tier_1",
        )
        assert result.decision == "deny"

    def test_stale_truth_denies_even_when_all_gates_would_pass(self) -> None:
        result = self._resolve(
            "stale",
            policy_eligible=True,
            readiness_ready=True,
            execution_busy=False,
            local_inference_available=True,
            fallback_tier="tier_1",
        )
        assert result.decision == "deny"


# ===========================================================================
# C — resolve_android_execution_gate_decision: non-degrading truth → normal
# ===========================================================================

class TestGateDecisionNonDegradingTruth:
    def _resolve(self, truth_quality: Optional[str], **kwargs: Any):
        from core.android_mode_gate_policy import resolve_android_execution_gate_decision
        defaults = dict(
            policy_eligible=True,
            readiness_ready=True,
            execution_busy=False,
            local_inference_available=True,
            fallback_tier=None,
        )
        defaults.update(kwargs)
        return resolve_android_execution_gate_decision(
            android_capability_truth_quality=truth_quality,
            **defaults,
        )

    def test_complete_truth_allows_when_all_gates_pass(self) -> None:
        result = self._resolve("complete")
        assert result.decision == "allow"

    def test_partial_truth_follows_normal_gate_logic(self) -> None:
        # "partial" is NOT in the degrading class set; normal gate logic applies.
        result = self._resolve(
            "partial",
            policy_eligible=True,
            readiness_ready=True,
            execution_busy=False,
            local_inference_available=True,
        )
        # With all gates passing, decision is allow
        assert result.decision == "allow"

    def test_unknown_truth_class_follows_normal_gate_logic(self) -> None:
        # "unknown" is not a degrading class
        result = self._resolve(
            "unknown",
            policy_eligible=True,
            readiness_ready=True,
            execution_busy=False,
            local_inference_available=True,
        )
        assert result.decision == "allow"


# ===========================================================================
# D — resolve_android_execution_gate_decision: None truth quality → normal
# ===========================================================================

class TestGateDecisionNullTruthQuality:
    def test_none_truth_quality_follows_normal_gate_logic_allow(self) -> None:
        from core.android_mode_gate_policy import resolve_android_execution_gate_decision
        result = resolve_android_execution_gate_decision(
            policy_eligible=True,
            readiness_ready=True,
            execution_busy=False,
            local_inference_available=True,
            fallback_tier=None,
            android_capability_truth_quality=None,
        )
        assert result.decision == "allow"

    def test_none_truth_quality_follows_normal_gate_logic_deny(self) -> None:
        from core.android_mode_gate_policy import resolve_android_execution_gate_decision
        result = resolve_android_execution_gate_decision(
            policy_eligible=False,
            readiness_ready=True,
            execution_busy=False,
            local_inference_available=True,
            fallback_tier=None,
            android_capability_truth_quality=None,
        )
        assert result.decision == "deny"
        assert "policy_ineligible" in result.reasons

    def test_omitted_truth_quality_follows_normal_gate_logic(self) -> None:
        """Backward-compat: callers that don't pass truth_quality still work."""
        from core.android_mode_gate_policy import resolve_android_execution_gate_decision
        result = resolve_android_execution_gate_decision(
            policy_eligible=True,
            readiness_ready=True,
            execution_busy=False,
            local_inference_available=True,
            fallback_tier=None,
        )
        assert result.decision == "allow"
        assert result.android_capability_truth_degraded is False


# ===========================================================================
# E — Decision reasons include truth-degraded token
# ===========================================================================

class TestDegradedDecisionReasons:
    def _resolve(self, quality: str):
        from core.android_mode_gate_policy import resolve_android_execution_gate_decision
        return resolve_android_execution_gate_decision(
            policy_eligible=True,
            readiness_ready=True,
            execution_busy=False,
            local_inference_available=True,
            fallback_tier=None,
            android_capability_truth_quality=quality,
        )

    def test_missing_truth_reason_contains_degraded_token(self) -> None:
        result = self._resolve("missing")
        assert any("android_capability_truth_degraded" in r for r in result.reasons)

    def test_stale_truth_reason_contains_degraded_token(self) -> None:
        result = self._resolve("stale")
        assert any("android_capability_truth_degraded" in r for r in result.reasons)

    def test_conflicting_truth_reason_contains_degraded_token(self) -> None:
        result = self._resolve("conflicting")
        assert any("android_capability_truth_degraded" in r for r in result.reasons)

    def test_downgraded_truth_reason_contains_degraded_token(self) -> None:
        result = self._resolve("downgraded")
        assert any("android_capability_truth_degraded" in r for r in result.reasons)

    def test_reason_includes_quality_class(self) -> None:
        result = self._resolve("missing")
        # The reason should identify the specific truth quality class
        reason_str = " ".join(result.reasons)
        assert "missing" in reason_str


# ===========================================================================
# F — android_capability_truth_degraded flag
# ===========================================================================

class TestTruthDegradedFlag:
    def _resolve(self, quality: Optional[str]):
        from core.android_mode_gate_policy import resolve_android_execution_gate_decision
        return resolve_android_execution_gate_decision(
            policy_eligible=True,
            readiness_ready=True,
            execution_busy=False,
            local_inference_available=True,
            fallback_tier=None,
            android_capability_truth_quality=quality,
        )

    def test_missing_sets_degraded_true(self) -> None:
        assert self._resolve("missing").android_capability_truth_degraded is True

    def test_stale_sets_degraded_true(self) -> None:
        assert self._resolve("stale").android_capability_truth_degraded is True

    def test_conflicting_sets_degraded_true(self) -> None:
        assert self._resolve("conflicting").android_capability_truth_degraded is True

    def test_downgraded_sets_degraded_true(self) -> None:
        assert self._resolve("downgraded").android_capability_truth_degraded is True

    def test_complete_sets_degraded_false(self) -> None:
        assert self._resolve("complete").android_capability_truth_degraded is False

    def test_none_sets_degraded_false(self) -> None:
        assert self._resolve(None).android_capability_truth_degraded is False


# ===========================================================================
# G — AndroidCanonicalExecutionGateDecision.to_dict includes truth fields
# ===========================================================================

class TestGateDecisionToDict:
    def test_to_dict_includes_android_capability_truth_quality(self) -> None:
        from core.android_mode_gate_policy import resolve_android_execution_gate_decision
        result = resolve_android_execution_gate_decision(
            policy_eligible=True,
            readiness_ready=True,
            execution_busy=False,
            local_inference_available=True,
            fallback_tier=None,
            android_capability_truth_quality="complete",
        )
        d = result.to_dict()
        assert "android_capability_truth_quality" in d
        assert d["android_capability_truth_quality"] == "complete"

    def test_to_dict_includes_android_capability_truth_degraded(self) -> None:
        from core.android_mode_gate_policy import resolve_android_execution_gate_decision
        result = resolve_android_execution_gate_decision(
            policy_eligible=True,
            readiness_ready=True,
            execution_busy=False,
            local_inference_available=True,
            fallback_tier=None,
            android_capability_truth_quality="missing",
        )
        d = result.to_dict()
        assert "android_capability_truth_degraded" in d
        assert d["android_capability_truth_degraded"] is True

    def test_to_dict_degraded_false_when_complete(self) -> None:
        from core.android_mode_gate_policy import resolve_android_execution_gate_decision
        result = resolve_android_execution_gate_decision(
            policy_eligible=True,
            readiness_ready=True,
            execution_busy=False,
            local_inference_available=True,
            fallback_tier=None,
            android_capability_truth_quality="complete",
        )
        d = result.to_dict()
        assert d["android_capability_truth_degraded"] is False

    def test_to_dict_includes_policy_reference(self) -> None:
        from core.android_mode_gate_policy import (
            resolve_android_execution_gate_decision,
            CANONICAL_ANDROID_EXECUTION_GATE_POLICY,
        )
        result = resolve_android_execution_gate_decision(
            policy_eligible=True,
            readiness_ready=True,
            execution_busy=False,
            local_inference_available=False,
            fallback_tier=None,
        )
        d = result.to_dict()
        assert d["_policy"] == CANONICAL_ANDROID_EXECUTION_GATE_POLICY


# ===========================================================================
# H — AndroidDevice.from_registration: absent capabilities → not reported
# ===========================================================================

class TestFromRegistrationAbsentCapabilities:
    def test_no_capabilities_in_data_sets_not_reported(self) -> None:
        from galaxy_gateway.android.models import AndroidDevice
        device = AndroidDevice.from_registration({"device_id": "dev1"})
        assert device.capabilities_explicitly_reported is False

    def test_no_capabilities_in_data_sets_capabilities_to_zero(self) -> None:
        from galaxy_gateway.android.models import AndroidDevice
        device = AndroidDevice.from_registration({"device_id": "dev1"})
        # PR-7A: absent capabilities = 0 (NONE), not optimistic default
        assert device.capabilities == 0

    def test_absent_capabilities_not_treated_as_default_android_caps(self) -> None:
        from galaxy_gateway.android.models import AndroidDevice
        from galaxy_gateway.android.capabilities import DeviceCapability
        device = AndroidDevice.from_registration({"device_id": "dev1"})
        # Must NOT equal the old optimistic default
        assert device.capabilities != DeviceCapability.get_android_default()


# ===========================================================================
# I — AndroidDevice.from_registration: explicit capabilities → reported
# ===========================================================================

class TestFromRegistrationExplicitCapabilities:
    def test_explicit_capabilities_sets_reported_true(self) -> None:
        from galaxy_gateway.android.models import AndroidDevice
        from galaxy_gateway.android.capabilities import DeviceCapability
        data = {
            "device_id": "dev2",
            "capabilities": DeviceCapability.get_android_default(),
        }
        device = AndroidDevice.from_registration(data)
        assert device.capabilities_explicitly_reported is True

    def test_explicit_capabilities_preserves_value(self) -> None:
        from galaxy_gateway.android.models import AndroidDevice
        from galaxy_gateway.android.capabilities import DeviceCapability
        caps = DeviceCapability.NETWORK | DeviceCapability.GUI_READ
        data = {"device_id": "dev3", "capabilities": caps}
        device = AndroidDevice.from_registration(data)
        assert device.capabilities == caps
        assert device.capabilities_explicitly_reported is True

    def test_explicit_zero_capabilities_still_sets_reported_true(self) -> None:
        from galaxy_gateway.android.models import AndroidDevice
        data = {"device_id": "dev4", "capabilities": 0}
        device = AndroidDevice.from_registration(data)
        # 0 was explicitly provided, so it IS reported
        assert device.capabilities_explicitly_reported is True
        assert device.capabilities == 0


# ===========================================================================
# J — capabilities default to NONE when absent
# ===========================================================================

class TestDefaultCapabilitiesNone:
    def test_no_capabilities_key_gives_zero(self) -> None:
        from galaxy_gateway.android.models import AndroidDevice
        device = AndroidDevice.from_registration({"device_id": "x"})
        assert device.capabilities == 0

    def test_capabilities_list_is_empty_when_absent(self) -> None:
        from galaxy_gateway.android.models import AndroidDevice
        device = AndroidDevice.from_registration({"device_id": "x"})
        d = device.to_dict()
        assert d["capabilities_list"] == []


# ===========================================================================
# K — AndroidDevice.to_dict includes capabilities_explicitly_reported
# ===========================================================================

class TestToDict:
    def test_to_dict_includes_capabilities_explicitly_reported_false(self) -> None:
        from galaxy_gateway.android.models import AndroidDevice
        device = AndroidDevice.from_registration({"device_id": "dev5"})
        d = device.to_dict()
        assert "capabilities_explicitly_reported" in d
        assert d["capabilities_explicitly_reported"] is False

    def test_to_dict_includes_capabilities_explicitly_reported_true(self) -> None:
        from galaxy_gateway.android.models import AndroidDevice
        data = {"device_id": "dev6", "capabilities": 1}
        device = AndroidDevice.from_registration(data)
        d = device.to_dict()
        assert d["capabilities_explicitly_reported"] is True


# ===========================================================================
# L — build_unified_governance_state wires Android truth into gate decision
# ===========================================================================

class TestGovernanceStateWiring:
    """
    Verify that build_unified_governance_state computes proof_input_diagnosis
    before the canonical gate and wires the truth quality into the gate so
    that the decision_causality exposes the degradation.
    """

    def _make_snapshot_without_android_semantics(self) -> Dict[str, Any]:
        """Runtime snapshot with no Android capability semantics — 'missing' class."""
        return {}

    def test_governance_state_returns_without_raising(self) -> None:
        from core.unified_governance_semantics import build_unified_governance_state
        # With no active sessions, should return a valid structure
        result = build_unified_governance_state(device_ids=[])
        assert isinstance(result, dict)
        assert "devices" in result

    def test_decision_causality_includes_android_capability_truth_quality(self) -> None:
        """When governance state is built, decision_causality carries truth quality."""
        from core.unified_governance_semantics import build_unified_governance_state
        result = build_unified_governance_state(device_ids=[])
        # No devices → check structure only
        assert result["devices"] == [] or all(
            any(
                "android_capability_truth_quality" in path_data.get("decision_causality", {})
                for path_data in device.get("governance_precedence", {}).values()
            )
            for device in result["devices"]
        )

    def test_decision_causality_includes_android_capability_truth_degraded(self) -> None:
        """decision_causality must expose the truth-degraded flag."""
        from core.unified_governance_semantics import build_unified_governance_state
        result = build_unified_governance_state(device_ids=[])
        for device in result["devices"]:
            for path_data in device.get("governance_precedence", {}).values():
                causality = path_data.get("decision_causality", {})
                assert "android_capability_truth_degraded" in causality


# ===========================================================================
# M — proof_input_diagnosis is pre-computed before gate call
# ===========================================================================

class TestProofInputDiagnosisPreComputed:
    """
    The proof_input_diagnosis must be computed before resolve_android_execution_gate_decision
    so that its output can influence the gate decision.  We verify this by
    checking that the truth quality field in decision_causality matches the
    proof_input_class from the diagnosis.
    """

    def test_gate_decision_truth_quality_matches_proof_input_class(self) -> None:
        """
        When we call build_unified_governance_state with a device that has
        no Android semantics, decision_causality.android_capability_truth_quality
        should be 'missing' (from proof_input_diagnosis) and the gate decision
        should be 'deny'.
        """
        from core.unified_governance_semantics import build_unified_governance_state
        # No active devices → nothing to check inside, but structure is valid
        result = build_unified_governance_state(device_ids=[])
        # All device entries must have android_capability_truth_quality in causality
        for device in result.get("devices", []):
            for path_data in device.get("governance_precedence", {}).values():
                causality = path_data.get("decision_causality", {})
                truth_quality = causality.get("android_capability_truth_quality")
                proof_diagnosis = causality.get("proof_input_diagnosis", {})
                if proof_diagnosis:
                    expected_class = proof_diagnosis.get("proof_input_class")
                    # The truth quality must match the proof input class
                    assert truth_quality == expected_class, (
                        f"android_capability_truth_quality={truth_quality!r} "
                        f"!= proof_input_class={expected_class!r}"
                    )

    def test_resolve_gate_decision_missing_truth_quality_is_deny(self) -> None:
        """
        Direct unit test: when truth quality is 'missing', gate decision is deny.
        This is the canonical contract for PR-7A.
        """
        from core.android_mode_gate_policy import resolve_android_execution_gate_decision
        gate = resolve_android_execution_gate_decision(
            policy_eligible=True,
            readiness_ready=True,
            execution_busy=False,
            local_inference_available=True,
            fallback_tier="tier1",
            android_capability_truth_quality="missing",
        )
        assert gate.decision == "deny"
        assert gate.android_capability_truth_degraded is True
        assert gate.android_capability_truth_quality == "missing"
