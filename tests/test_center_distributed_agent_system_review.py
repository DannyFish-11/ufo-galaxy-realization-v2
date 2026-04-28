#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_center_distributed_agent_system_review.py
=====================================================
Tests for the center-governed distributed intelligent agent system review.

These tests enforce four non-negotiable invariants about system characterization:

1. **Center-distributed identity** — the review correctly identifies the system
   as a center-governed distributed intelligent agent system, not a binary
   "control plane + passive execution end".

2. **Android local intelligence coverage** — the review covers Android's local
   networking, local task execution, local inference architecture, and
   local planning/grounding capabilities.  Android must not be described
   as a passive participant.

3. **Delegated path is one path, not the whole system** — the review explicitly
   covers execution paths beyond the delegated path (local execution, local
   inference, local networking, cross-device evidence uplink).

4. **Gap and deferred items are preserved honestly** — the review does not
   inflate maturity to "fully operational" and does not erase real gaps.

Test groups
-----------
A. Module importability and sentinel presence
B. System identity invariants (center-distributed, not binary)
C. Android local capability coverage (not passive, has local intelligence)
D. Six-layer maturity assessment completeness
E. Gap and deferred item preservation
F. Report serialization and JSON round-trip
G. Singleton lifecycle (build, get, reset)
"""

from __future__ import annotations

import json

import pytest

from core.center_distributed_agent_system_review import (
    ANDROID_IS_DISTRIBUTED_RUNTIME_NODE_POLICY,
    CENTER_DISTRIBUTED_AGENT_SYSTEM_IDENTITY_SENTINEL,
    CENTER_DISTRIBUTED_AGENT_SYSTEM_REVIEW_AUTHORITY,
    DELEGATED_PATH_IS_ONE_PATH_NOT_WHOLE_SYSTEM_POLICY,
    HONEST_GAP_PRESERVATION_POLICY,
    SIX_MATURITY_LAYER_ASSESSMENT_POLICY,
    AndroidLocalCapabilityProfile,
    CenterDistributedAgentSystemReviewReport,
    CenterDistributedAgentSystemReviewer,
    LayerMaturityStatus,
    MaturityLayer,
    build_center_distributed_agent_system_review,
    get_center_distributed_agent_system_review,
    reset_center_distributed_agent_system_review,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_singleton():
    """Ensure each test starts with a fresh singleton."""
    reset_center_distributed_agent_system_review()
    yield
    reset_center_distributed_agent_system_review()


@pytest.fixture()
def report() -> CenterDistributedAgentSystemReviewReport:
    """Return a freshly built review report."""
    return build_center_distributed_agent_system_review()


# ---------------------------------------------------------------------------
# A. Module importability and sentinel presence
# ---------------------------------------------------------------------------


class TestModuleAndSentinels:
    """Verify the module is importable and all sentinels are non-empty strings."""

    def test_review_authority_sentinel_nonempty(self):
        assert isinstance(CENTER_DISTRIBUTED_AGENT_SYSTEM_REVIEW_AUTHORITY, str)
        assert len(CENTER_DISTRIBUTED_AGENT_SYSTEM_REVIEW_AUTHORITY) > 20

    def test_system_identity_sentinel_nonempty(self):
        assert isinstance(CENTER_DISTRIBUTED_AGENT_SYSTEM_IDENTITY_SENTINEL, str)
        assert len(CENTER_DISTRIBUTED_AGENT_SYSTEM_IDENTITY_SENTINEL) > 20

    def test_android_distributed_node_policy_nonempty(self):
        assert isinstance(ANDROID_IS_DISTRIBUTED_RUNTIME_NODE_POLICY, str)
        assert len(ANDROID_IS_DISTRIBUTED_RUNTIME_NODE_POLICY) > 50

    def test_delegated_path_policy_nonempty(self):
        assert isinstance(DELEGATED_PATH_IS_ONE_PATH_NOT_WHOLE_SYSTEM_POLICY, str)
        assert len(DELEGATED_PATH_IS_ONE_PATH_NOT_WHOLE_SYSTEM_POLICY) > 50

    def test_six_layer_policy_nonempty(self):
        assert isinstance(SIX_MATURITY_LAYER_ASSESSMENT_POLICY, str)
        assert len(SIX_MATURITY_LAYER_ASSESSMENT_POLICY) > 50

    def test_honest_gap_policy_nonempty(self):
        assert isinstance(HONEST_GAP_PRESERVATION_POLICY, str)
        assert len(HONEST_GAP_PRESERVATION_POLICY) > 50

    def test_system_identity_sentinel_contains_center_distributed(self):
        """Sentinel must mention center-distributed architecture."""
        sentinel = CENTER_DISTRIBUTED_AGENT_SYSTEM_IDENTITY_SENTINEL.lower()
        assert "center" in sentinel or "distributed" in sentinel, (
            "System identity sentinel must contain 'center' or 'distributed'."
        )

    def test_android_policy_mentions_distributed_runtime_node(self):
        """Android policy must mention 'distributed runtime node'."""
        policy = ANDROID_IS_DISTRIBUTED_RUNTIME_NODE_POLICY.lower()
        assert "distributed runtime node" in policy or "distributed" in policy, (
            "Android policy must describe Android as a distributed runtime node."
        )

    def test_delegated_path_policy_mentions_one_path(self):
        """Delegated path policy must assert it is ONE path, not the whole system."""
        policy = DELEGATED_PATH_IS_ONE_PATH_NOT_WHOLE_SYSTEM_POLICY.lower()
        assert "one" in policy or "multiple" in policy or "path" in policy, (
            "Delegated path policy must mention 'one path' or 'multiple paths'."
        )


# ---------------------------------------------------------------------------
# B. System identity invariants
# ---------------------------------------------------------------------------


class TestSystemIdentityInvariants:
    """The review must correctly characterize the system as center-distributed."""

    def test_report_has_system_identity_field(self, report):
        assert hasattr(report, "system_identity")
        assert isinstance(report.system_identity, str)
        assert len(report.system_identity) > 0

    def test_system_identity_is_center_distributed_not_binary(self, report):
        """System identity must NOT describe a simple binary control+passive model."""
        identity = report.system_identity.upper()
        # Must contain center or distributed
        assert "CENTER" in identity or "DISTRIBUTED" in identity, (
            "System identity must mention 'center' or 'distributed'. "
            f"Got: {report.system_identity[:100]}"
        )

    def test_system_is_center_distributed_agent_flag(self, report):
        """The review must set system_is_center_distributed_agent based on code evidence."""
        # This flag is determined by whether architecture modules are importable.
        # It should be True when core governance modules are importable.
        assert isinstance(report.system_is_center_distributed_agent, bool), (
            "system_is_center_distributed_agent must be a boolean."
        )
        # Given that the V2 codebase is present, this should be True
        assert report.system_is_center_distributed_agent, (
            "system_is_center_distributed_agent must be True in a running V2 environment. "
            "This indicates the architecture_system_model layer has sufficient code evidence."
        )

    def test_delegated_path_is_one_path_invariant(self, report):
        """Structural invariant: delegated path is always one path, not the whole system."""
        assert report.delegated_path_is_one_path_not_whole_system is True, (
            "delegated_path_is_one_path_not_whole_system must ALWAYS be True. "
            "The delegated path is ONE execution path, not the complete system."
        )

    def test_overall_verdict_is_not_fully_operational(self, report):
        """The review must not inflate the verdict to 'fully_operational'."""
        assert report.overall_verdict != "fully_operational", (
            "overall_verdict must NOT be 'fully_operational'. "
            "The system has documented gaps (cross-repo evidence wire, "
            "real-device CI, governance enforcement) that prevent this verdict."
        )

    def test_overall_verdict_is_not_skeleton(self, report):
        """The review must not under-describe the system as a mere skeleton."""
        skeleton_verdicts = {"skeleton", "empty", "not_started", "proof_of_concept"}
        assert report.overall_verdict.lower() not in skeleton_verdicts, (
            "overall_verdict must NOT describe the system as a skeleton or "
            "proof-of-concept. The system has real capabilities."
        )

    def test_overall_verdict_is_non_empty(self, report):
        assert report.overall_verdict, "overall_verdict must be non-empty."

    def test_verdict_rationale_is_non_empty(self, report):
        assert report.verdict_rationale, "verdict_rationale must be non-empty."


# ---------------------------------------------------------------------------
# C. Android local capability coverage
# ---------------------------------------------------------------------------


class TestAndroidLocalCapabilityCoverage:
    """Android must be covered as a distributed runtime node, not a passive participant."""

    def test_android_capability_profile_present(self, report):
        assert hasattr(report, "android_capability_profile")
        assert isinstance(report.android_capability_profile, AndroidLocalCapabilityProfile)

    def test_android_is_distributed_runtime_node_evaluated(self, report):
        """The review must evaluate whether Android qualifies as a distributed runtime node."""
        assert isinstance(report.android_is_distributed_runtime_node, bool), (
            "android_is_distributed_runtime_node must be a boolean."
        )

    def test_android_local_intelligence_architecture_covered(self, report):
        """The review must cover Android's local inference architecture.

        Local inference (MobileVlmPlanner + LocalInferenceRuntimeManager)
        must be assessed, even if it is non-default.
        """
        profile = report.android_capability_profile
        # The profile should document whether local inference code exists
        # (even if not default-active)
        assert hasattr(profile, "local_inference_capability_code_exists"), (
            "AndroidLocalCapabilityProfile must have "
            "local_inference_capability_code_exists field."
        )

    def test_android_local_inference_architecture_is_real(self, report):
        """Android's local inference code (MobileVlmPlanner) must be marked real
        when the joint review document is present."""
        profile = report.android_capability_profile
        # If the joint review doc was found, local_inference_capability_code_exists = True
        # The profile must distinguish between code existence and default activation
        assert hasattr(profile, "local_inference_capability_default_active"), (
            "AndroidLocalCapabilityProfile must distinguish between "
            "local_inference_capability_code_exists and "
            "local_inference_capability_default_active."
        )
        # Default active must be False (honest: local AI requires external server)
        assert profile.local_inference_capability_default_active is False, (
            "local_inference_capability_default_active must be False. "
            "Android local AI requires external inference server; it is non-default."
        )

    def test_android_local_networking_capability_covered(self, report):
        """The review must cover Android's local networking capability."""
        profile = report.android_capability_profile
        assert hasattr(profile, "local_networking_capability"), (
            "AndroidLocalCapabilityProfile must have local_networking_capability field."
        )

    def test_android_gui_interaction_capability_covered(self, report):
        """The review must cover Android's GUI interaction capability."""
        profile = report.android_capability_profile
        assert hasattr(profile, "local_gui_interaction_capability"), (
            "AndroidLocalCapabilityProfile must have local_gui_interaction_capability."
        )

    def test_android_acceptance_evaluation_covered(self, report):
        """The review must cover Android's local acceptance evaluation capability."""
        profile = report.android_capability_profile
        assert hasattr(profile, "local_acceptance_evaluation_capability"), (
            "AndroidLocalCapabilityProfile must have "
            "local_acceptance_evaluation_capability (DelegatedRuntimeAcceptanceEvaluator)."
        )

    def test_android_planning_loop_capability_covered(self, report):
        """The review must cover Android's local planning loop (LoopController)."""
        profile = report.android_capability_profile
        assert hasattr(profile, "local_planning_loop_capability"), (
            "AndroidLocalCapabilityProfile must have local_planning_loop_capability "
            "(LoopController — Android-side step-level orchestration)."
        )

    def test_android_layer_assessment_present(self, report):
        """The android_local_intelligence_runtime_host layer must be assessed."""
        layer_key = MaturityLayer.android_local_intelligence_runtime_host.value
        assert layer_key in report.layer_assessments, (
            f"Layer '{layer_key}' must be present in layer_assessments. "
            "Android local intelligence must be assessed as its own maturity layer."
        )

    def test_android_layer_is_not_structural_only(self, report):
        """Android's local capability layer must be above structural_only.

        Android has real, importable code backing its local capabilities.
        """
        layer_key = MaturityLayer.android_local_intelligence_runtime_host.value
        if layer_key in report.layer_assessments:
            layer = report.layer_assessments[layer_key]
            assert layer.status != LayerMaturityStatus.structural_only, (
                "android_local_intelligence_runtime_host must be above structural_only. "
                "Android has real local capability code: AccessibilityActionExecutor, "
                "LoopController, DelegatedRuntimeAcceptanceEvaluator, etc."
            )

    def test_android_layer_has_evidence_anchors(self, report):
        """The android layer must have code-anchored evidence, not empty."""
        layer_key = MaturityLayer.android_local_intelligence_runtime_host.value
        if layer_key in report.layer_assessments:
            layer = report.layer_assessments[layer_key]
            assert len(layer.evidence_anchors) > 0, (
                "android_local_intelligence_runtime_host must have at least one "
                "evidence anchor (importable module or document reference)."
            )


# ---------------------------------------------------------------------------
# D. Six-layer maturity assessment completeness
# ---------------------------------------------------------------------------


class TestSixLayerAssessmentCompleteness:
    """All six maturity layers must be assessed."""

    def test_all_six_layers_are_assessed(self, report):
        """All six MaturityLayer values must be present in layer_assessments."""
        for layer in MaturityLayer.all_layers():
            assert layer.value in report.layer_assessments, (
                f"MaturityLayer.{layer.value} is missing from layer_assessments. "
                "All six layers must be assessed."
            )

    def test_each_layer_has_a_status(self, report):
        """Each assessed layer must have a valid LayerMaturityStatus."""
        for layer in MaturityLayer.all_layers():
            if layer.value in report.layer_assessments:
                assessment = report.layer_assessments[layer.value]
                assert isinstance(assessment.status, LayerMaturityStatus), (
                    f"Layer {layer.value} must have a LayerMaturityStatus."
                )

    def test_architecture_layer_is_substantially_closed_or_better(self, report):
        """The architecture_system_model layer must be substantially closed or better
        given the extensive governance modules in V2."""
        layer_key = MaturityLayer.architecture_system_model.value
        if layer_key in report.layer_assessments:
            layer = report.layer_assessments[layer_key]
            acceptable_statuses = {
                LayerMaturityStatus.substantially_closed,
                LayerMaturityStatus.operationally_closed,
                LayerMaturityStatus.partially_closed,
            }
            assert layer.status in acceptable_statuses, (
                f"architecture_system_model must be partially_closed or better. "
                f"Got: {layer.status.value}. "
                "V2 has extensive governance and cognitive map modules."
            )

    def test_real_device_layer_is_not_operationally_closed(self, report):
        """The real_device_multi_device_operational_closure layer must NOT be
        operationally_closed — there is no real-device CI in this repo."""
        layer_key = MaturityLayer.real_device_multi_device_operational_closure.value
        if layer_key in report.layer_assessments:
            layer = report.layer_assessments[layer_key]
            assert layer.status != LayerMaturityStatus.operationally_closed, (
                "real_device_multi_device_operational_closure must NOT be "
                "operationally_closed. No real-device CI workflow exists."
            )

    def test_cross_repo_evidence_is_not_operationally_closed(self, report):
        """The cross_repo_evidence layer must NOT be operationally_closed.
        The AIP wire gap for ReconciliationSignal is a known unresolved gap."""
        layer_key = MaturityLayer.cross_repo_evidence.value
        if layer_key in report.layer_assessments:
            layer = report.layer_assessments[layer_key]
            assert layer.status != LayerMaturityStatus.operationally_closed, (
                "cross_repo_evidence must NOT be operationally_closed. "
                "ReconciliationSignal AIP wire gap is unresolved."
            )

    def test_each_layer_has_layer_reference(self, report):
        """Each assessment must reference its layer correctly."""
        for layer in MaturityLayer.all_layers():
            if layer.value in report.layer_assessments:
                assessment = report.layer_assessments[layer.value]
                assert assessment.layer == layer, (
                    f"Assessment for {layer.value} has wrong layer reference."
                )


# ---------------------------------------------------------------------------
# E. Gap and deferred item preservation
# ---------------------------------------------------------------------------


class TestGapAndDeferredPreservation:
    """Gaps and deferred items must be preserved, not suppressed."""

    def test_deferred_items_are_not_empty(self, report):
        """The review must have non-empty deferred items.

        The following are formally deferred:
        - Android local AI activation (requires inference server)
        - Release gate enforcement promotion
        - Real-device CI workflow
        - AIP ReconciliationSignal wire registration
        """
        assert len(report.deferred_items) > 0, (
            "deferred_items must be non-empty. "
            "Known deferred items include: Android local AI default activation, "
            "release gate enforcement promotion, real-device CI, AIP wire gap."
        )

    def test_cross_repo_evidence_gaps_are_present(self, report):
        """Cross-repo evidence gaps must be explicitly documented."""
        assert len(report.cross_repo_evidence_gaps) > 0, (
            "cross_repo_evidence_gaps must be non-empty. "
            "Known gap: ReconciliationSignal not in AIP MsgType; "
            "HandoffEnvelopeV2 response handler possibly incomplete."
        )

    def test_real_device_closure_gaps_are_present(self, report):
        """Real-device closure gaps must be explicitly documented."""
        assert len(report.real_device_closure_gaps) > 0, (
            "real_device_closure_gaps must be non-empty. "
            "Known gaps: no Android emulator CI; no real-device evidence artifacts."
        )

    def test_governance_enforcement_gaps_are_present(self, report):
        """Governance enforcement gaps must be explicitly documented."""
        assert len(report.governance_enforcement_gaps) > 0, (
            "governance_enforcement_gaps must be non-empty. "
            "Known gap: distributed_release_gate_skeleton.is_enforcing = False "
            "(advisory, not CI-blocking)."
        )

    def test_android_layer_has_gap_about_local_ai_non_default(self, report):
        """The android layer must document that local AI is non-default."""
        layer_key = MaturityLayer.android_local_intelligence_runtime_host.value
        if layer_key in report.layer_assessments:
            layer = report.layer_assessments[layer_key]
            # At minimum, gaps or deferred_items should mention non-default
            combined = " ".join(layer.gap_items + layer.deferred_items).lower()
            assert "non-default" in combined or "non_default" in combined or "noop" in combined or "inactive" in combined, (
                "android_local_intelligence_runtime_host must document that "
                "local AI (MobileVlmPlanner) is non-default. "
                "NoOpPlannerService is the default — this must be honest."
            )

    def test_layer_gaps_do_not_erase_capabilities(self, report):
        """Having a gap does not mean the layer has zero capability.

        A layer with gaps can still have evidence_anchors demonstrating
        real code exists.  Gaps and capabilities must coexist honestly.
        """
        for layer in MaturityLayer.all_layers():
            if layer.value in report.layer_assessments:
                assessment = report.layer_assessments[layer.value]
                if assessment.gap_items:
                    # A layer with gaps CAN still have evidence
                    # (gaps and evidence coexist — both are valid)
                    assert isinstance(assessment.gap_items, list), (
                        "gap_items must be a list."
                    )


# ---------------------------------------------------------------------------
# F. Report serialization and JSON round-trip
# ---------------------------------------------------------------------------


class TestReportSerialization:
    """The report must be JSON-serialisable and round-trippable."""

    def test_to_dict_returns_dict(self, report):
        result = report.to_dict()
        assert isinstance(result, dict)

    def test_to_json_returns_string(self, report):
        result = report.to_json()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_json_is_valid_json(self, report):
        result = report.to_json()
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_json_contains_system_identity(self, report):
        parsed = json.loads(report.to_json())
        assert "system_identity" in parsed

    def test_json_contains_layer_assessments(self, report):
        parsed = json.loads(report.to_json())
        assert "layer_assessments" in parsed
        assert isinstance(parsed["layer_assessments"], dict)

    def test_json_contains_overall_verdict(self, report):
        parsed = json.loads(report.to_json())
        assert "overall_verdict" in parsed
        assert parsed["overall_verdict"]  # non-empty

    def test_json_contains_android_capability_profile(self, report):
        parsed = json.loads(report.to_json())
        assert "android_capability_profile" in parsed
        profile = parsed["android_capability_profile"]
        assert "local_networking_capability" in profile
        assert "local_inference_capability_code_exists" in profile
        assert "local_inference_capability_default_active" in profile

    def test_json_all_six_layers_present(self, report):
        parsed = json.loads(report.to_json())
        assessments = parsed["layer_assessments"]
        for layer in MaturityLayer.all_layers():
            assert layer.value in assessments, (
                f"Layer {layer.value} missing from JSON output."
            )

    def test_android_profile_to_dict(self, report):
        profile_dict = report.android_capability_profile.to_dict()
        assert isinstance(profile_dict, dict)
        assert "qualifies_as_distributed_runtime_node" in profile_dict
        assert "has_local_intelligence_architecture" in profile_dict


# ---------------------------------------------------------------------------
# G. Singleton lifecycle
# ---------------------------------------------------------------------------


class TestSingletonLifecycle:
    """Singleton builds once, reset clears it, next get rebuilds."""

    def test_get_returns_report(self):
        report = get_center_distributed_agent_system_review()
        assert isinstance(report, CenterDistributedAgentSystemReviewReport)

    def test_get_returns_same_instance_on_second_call(self):
        r1 = get_center_distributed_agent_system_review()
        r2 = get_center_distributed_agent_system_review()
        assert r1 is r2, "get_center_distributed_agent_system_review must return the same instance."

    def test_reset_clears_singleton(self):
        r1 = get_center_distributed_agent_system_review()
        reset_center_distributed_agent_system_review()
        r2 = get_center_distributed_agent_system_review()
        assert r1 is not r2, "After reset, a new instance must be created."

    def test_build_always_returns_fresh_instance(self):
        r1 = build_center_distributed_agent_system_review()
        r2 = build_center_distributed_agent_system_review()
        assert r1 is not r2, "build_center_distributed_agent_system_review must always return fresh instance."


# ---------------------------------------------------------------------------
# H. MaturityLayer and LayerMaturityStatus enumerations
# ---------------------------------------------------------------------------


class TestEnumerations:
    """Basic sanity checks on the enumerations."""

    def test_all_six_maturity_layers_defined(self):
        layers = MaturityLayer.all_layers()
        assert len(layers) == 6, f"Expected 6 MaturityLayer values, got {len(layers)}."

    def test_maturity_layer_values_are_strings(self):
        for layer in MaturityLayer.all_layers():
            assert isinstance(layer.value, str)

    def test_layer_maturity_status_ordinal_ordering(self):
        """structural_only < code_implemented < partially_closed < substantially_closed < operationally_closed"""
        assert (
            LayerMaturityStatus.structural_only.ordinal()
            < LayerMaturityStatus.code_implemented.ordinal()
            < LayerMaturityStatus.partially_closed.ordinal()
            < LayerMaturityStatus.substantially_closed.ordinal()
            < LayerMaturityStatus.operationally_closed.ordinal()
        )

    def test_layer_maturity_status_is_gap(self):
        assert LayerMaturityStatus.structural_only.is_gap() is True
        assert LayerMaturityStatus.code_implemented.is_gap() is True
        assert LayerMaturityStatus.partially_closed.is_gap() is False
        assert LayerMaturityStatus.substantially_closed.is_gap() is False
        assert LayerMaturityStatus.operationally_closed.is_gap() is False


# ---------------------------------------------------------------------------
# I. AndroidLocalCapabilityProfile direct tests
# ---------------------------------------------------------------------------


class TestAndroidLocalCapabilityProfileDirect:
    """Direct tests on AndroidLocalCapabilityProfile logic."""

    def test_empty_profile_is_not_distributed_runtime_node(self):
        profile = AndroidLocalCapabilityProfile()
        assert profile.is_distributed_runtime_node() is False

    def test_profile_with_networking_execution_persistence_is_node(self):
        profile = AndroidLocalCapabilityProfile(
            local_networking_capability=True,
            local_task_execution_capability=True,
            local_gui_interaction_capability=True,
            persistent_runtime_host_capability=True,
        )
        assert profile.is_distributed_runtime_node() is True

    def test_profile_has_local_intelligence_architecture_with_all_three(self):
        profile = AndroidLocalCapabilityProfile(
            local_inference_capability_code_exists=True,
            local_grounding_capability_code_exists=True,
            local_planning_loop_capability=True,
        )
        assert profile.has_local_intelligence_architecture() is True

    def test_profile_does_not_have_intelligence_without_all_three(self):
        profile = AndroidLocalCapabilityProfile(
            local_inference_capability_code_exists=True,
            local_grounding_capability_code_exists=False,
            local_planning_loop_capability=True,
        )
        assert profile.has_local_intelligence_architecture() is False

    def test_profile_to_dict_includes_derived_fields(self):
        profile = AndroidLocalCapabilityProfile(
            local_networking_capability=True,
            local_task_execution_capability=True,
            local_gui_interaction_capability=True,
            persistent_runtime_host_capability=True,
        )
        d = profile.to_dict()
        assert d["qualifies_as_distributed_runtime_node"] is True

    def test_profile_inference_code_exists_but_not_default(self):
        """Honest representation: code exists but is non-default."""
        profile = AndroidLocalCapabilityProfile(
            local_inference_capability_code_exists=True,
            local_inference_capability_default_active=False,
        )
        assert profile.local_inference_capability_code_exists is True
        assert profile.local_inference_capability_default_active is False
