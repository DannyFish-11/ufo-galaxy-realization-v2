#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_capability_aware_routing_default.py
===============================================
Automated validation for capability-aware routing as the default main path.

Problem addressed
-----------------
This test suite validates the PR fix for the structural gap where:
  1. Explicit ``device_id`` could bypass capability-aware routing.
  2. Capability-aware routing was opt-in (only when ``required_capabilities``
     was explicitly declared), not the default main path.
  3. Capability mismatch was warning-only rather than a routing constraint.

Test groups
-----------
A) Sentinels — all policy sentinels importable and expressive.
B) capability-best-match routing — no explicit device_id; capability graph
   drives participant selection.
C) Multi-device capability selection — multiple devices with different
   capability profiles; best-match is selected.
D) Capability mismatch REJECT — explicit device_id with wrong capabilities
   and no capable alternative → CAPABILITY_REJECTED (not a warning).
E) Capability mismatch REROUTE — explicit device_id with wrong capabilities
   but capable alternatives exist → CAPABILITY_REROUTED to alternative.
F) Explicit override in exception path — tool with no inferrable capabilities;
   explicit device_id proceeds as EXPLICIT_OVERRIDE (audited exception).
G) Capability inference from tool_name — command_router inference wiring.
H) mainline_routing_enforcement new sentinels — EXPLICIT_ROUTE_IS_EXCEPTION_PATH
   and CAPABILITY_AWARE_ROUTING_IS_DEFAULT_MAINLINE importable.
I) apply_capability_aware_default integrations — all outcome paths correct.
"""

from __future__ import annotations

from typing import Any, List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# A) Sentinels
# ===========================================================================


class TestCapabilityAwareRoutingDefaultSentinels:
    """All policy sentinels are importable and contain expected keywords."""

    def test_authority_sentinel_importable(self):
        from core.capability_aware_routing_default import (
            CAPABILITY_AWARE_ROUTING_DEFAULT_AUTHORITY,
        )

        assert CAPABILITY_AWARE_ROUTING_DEFAULT_AUTHORITY
        assert "AUTHORITY" in CAPABILITY_AWARE_ROUTING_DEFAULT_AUTHORITY

    def test_default_mainline_policy_importable(self):
        from core.capability_aware_routing_default import (
            CAPABILITY_AWARE_ROUTING_IS_DEFAULT_MAINLINE_POLICY,
        )

        assert "default" in CAPABILITY_AWARE_ROUTING_IS_DEFAULT_MAINLINE_POLICY.lower()
        assert "capability" in CAPABILITY_AWARE_ROUTING_IS_DEFAULT_MAINLINE_POLICY.lower()

    def test_exception_path_policy_importable(self):
        from core.capability_aware_routing_default import (
            EXPLICIT_DEVICE_ID_IS_EXCEPTION_PATH_POLICY,
        )

        assert "exception" in EXPLICIT_DEVICE_ID_IS_EXCEPTION_PATH_POLICY.lower()
        assert "device_id" in EXPLICIT_DEVICE_ID_IS_EXCEPTION_PATH_POLICY

    def test_mismatch_constraint_policy_importable(self):
        from core.capability_aware_routing_default import (
            CAPABILITY_MISMATCH_IS_ROUTING_CONSTRAINT_POLICY,
        )

        assert "constraint" in CAPABILITY_MISMATCH_IS_ROUTING_CONSTRAINT_POLICY.lower()
        assert "warning" in CAPABILITY_MISMATCH_IS_ROUTING_CONSTRAINT_POLICY.lower()


# ===========================================================================
# B) Capability best-match routing (default main path, no explicit device_id)
# ===========================================================================


class _FakeExecutor:
    """Minimal executor stub with a node_id attribute."""

    def __init__(self, node_id: str):
        self.node_id = node_id


class TestCapabilityBestMatchRouting:
    """No explicit device_id — capability graph drives participant selection."""

    def test_no_explicit_target_with_capability_match(self):
        """When no explicit target is given and a capable device exists,
        outcome is CAPABILITY_MATCHED with the capable device recommended."""
        from core.capability_aware_routing_default import (
            apply_capability_aware_default,
            CapabilityRoutingOutcome,
        )

        executors = [_FakeExecutor("device-camera-1")]
        decision = apply_capability_aware_default(
            tool_name="take_photo",
            explicit_targets=[],
            routable_executors=executors,
        )

        assert decision.outcome == CapabilityRoutingOutcome.CAPABILITY_MATCHED
        assert "device-camera-1" in decision.recommended_targets
        assert decision.is_explicit_override is False

    def test_no_explicit_target_capability_matched_multiple_candidates(self):
        """Multiple capable devices are all recommended when none is explicitly
        chosen — capability graph provides all candidates."""
        from core.capability_aware_routing_default import (
            apply_capability_aware_default,
            CapabilityRoutingOutcome,
        )

        executors = [
            _FakeExecutor("device-a"),
            _FakeExecutor("device-b"),
        ]
        decision = apply_capability_aware_default(
            tool_name="take_photo",
            explicit_targets=[],
            routable_executors=executors,
        )

        assert decision.outcome == CapabilityRoutingOutcome.CAPABILITY_MATCHED
        assert set(decision.recommended_targets) == {"device-a", "device-b"}
        assert decision.applied_capabilities  # caps were resolved (from inference)

    def test_no_explicit_target_no_executors_returns_insufficient_data(self):
        """When no target is given and the capability graph is empty, the
        outcome is INSUFFICIENT_DATA — not a silent bypass."""
        from core.capability_aware_routing_default import (
            apply_capability_aware_default,
            CapabilityRoutingOutcome,
        )

        decision = apply_capability_aware_default(
            tool_name="take_photo",
            explicit_targets=[],
            routable_executors=[],
        )

        assert decision.outcome == CapabilityRoutingOutcome.INSUFFICIENT_DATA
        assert decision.recommended_targets == []

    def test_no_requirements_inferrable_and_no_explicit_target_is_noop(self):
        """When neither explicit caps nor inferred caps exist and no target is
        given, outcome is NO_REQUIREMENTS (backward-compatible no-op)."""
        from core.capability_aware_routing_default import (
            apply_capability_aware_default,
            CapabilityRoutingOutcome,
        )

        decision = apply_capability_aware_default(
            tool_name="unknown_unregistered_command_xyz",
            explicit_targets=[],
            routable_executors=[_FakeExecutor("device-a")],
        )

        assert decision.outcome == CapabilityRoutingOutcome.NO_REQUIREMENTS


# ===========================================================================
# C) Multi-device capability selection
# ===========================================================================


class TestMultiDeviceCapabilitySelection:
    """Multiple devices with different capability profiles; best-match selected."""

    def test_explicit_caps_match_subset_of_devices(self):
        """Given two candidates but only one is in the routable set for the
        required capabilities, routing selects the capable device."""
        from core.capability_aware_routing_default import (
            apply_capability_aware_default,
            CapabilityRoutingOutcome,
        )

        # Only 'device-capable' is in the routable executors for 'camera'
        executors = [_FakeExecutor("device-capable")]
        decision = apply_capability_aware_default(
            tool_name="take_photo",
            explicit_targets=[],
            routable_executors=executors,
            required_capabilities=["camera"],
        )

        assert decision.outcome == CapabilityRoutingOutcome.CAPABILITY_MATCHED
        assert decision.recommended_targets == ["device-capable"]

    def test_explicit_target_confirmed_in_capability_graph(self):
        """When the explicit target IS in the capability graph, routing
        proceeds with that device (CAPABILITY_MATCHED)."""
        from core.capability_aware_routing_default import (
            apply_capability_aware_default,
            CapabilityRoutingOutcome,
        )

        executors = [_FakeExecutor("device-capable"), _FakeExecutor("device-other")]
        decision = apply_capability_aware_default(
            tool_name="take_photo",
            explicit_targets=["device-capable"],
            routable_executors=executors,
            required_capabilities=["camera"],
        )

        assert decision.outcome == CapabilityRoutingOutcome.CAPABILITY_MATCHED
        assert "device-capable" in decision.recommended_targets
        assert decision.original_explicit_targets == ["device-capable"]

    def test_multi_device_all_confirmed_capability_matched(self):
        """Multiple explicit targets are all confirmed → CAPABILITY_MATCHED."""
        from core.capability_aware_routing_default import (
            apply_capability_aware_default,
            CapabilityRoutingOutcome,
        )

        executors = [_FakeExecutor("dev-1"), _FakeExecutor("dev-2")]
        decision = apply_capability_aware_default(
            tool_name="take_photo",
            explicit_targets=["dev-1", "dev-2"],
            routable_executors=executors,
            required_capabilities=["camera"],
        )

        assert decision.outcome == CapabilityRoutingOutcome.CAPABILITY_MATCHED
        assert set(decision.recommended_targets) == {"dev-1", "dev-2"}

    def test_multi_device_partial_confirmed_filters_to_confirmed_subset(self):
        """When some explicit targets are confirmed and some are not, routing
        filters to the confirmed subset only."""
        from core.capability_aware_routing_default import (
            apply_capability_aware_default,
            CapabilityRoutingOutcome,
        )

        executors = [_FakeExecutor("dev-capable")]
        decision = apply_capability_aware_default(
            tool_name="take_photo",
            explicit_targets=["dev-capable", "dev-incapable"],
            routable_executors=executors,
            required_capabilities=["camera"],
        )

        assert decision.outcome == CapabilityRoutingOutcome.CAPABILITY_MATCHED
        assert "dev-capable" in decision.recommended_targets
        assert "dev-incapable" not in decision.recommended_targets


# ===========================================================================
# D) Capability mismatch REJECT
# ===========================================================================


class TestCapabilityMismatchReject:
    """Explicit device_id with wrong capabilities and no alternatives → REJECTED."""

    def test_explicit_target_not_in_graph_and_no_alternative_is_rejected(self):
        """When an explicit target is not in the capability graph and there
        are no capable alternatives, the outcome is CAPABILITY_REJECTED.
        This is a structured rejection, NOT a warning-only bypass."""
        from core.capability_aware_routing_default import (
            apply_capability_aware_default,
            CapabilityRoutingOutcome,
        )

        # The routable graph is empty → no capable alternatives
        decision = apply_capability_aware_default(
            tool_name="take_photo",
            explicit_targets=["device-incapable"],
            routable_executors=[],
            required_capabilities=["camera"],
        )

        assert decision.outcome == CapabilityRoutingOutcome.CAPABILITY_REJECTED
        assert decision.recommended_targets == []
        assert "device-incapable" in decision.original_explicit_targets

    def test_capability_rejected_reason_mentions_caps(self):
        """The rejection reason must mention the required capabilities so
        the error is actionable."""
        from core.capability_aware_routing_default import (
            apply_capability_aware_default,
        )

        decision = apply_capability_aware_default(
            tool_name="take_photo",
            explicit_targets=["bad-device"],
            routable_executors=[],
            required_capabilities=["camera"],
        )

        assert "camera" in decision.reason

    def test_mismatch_with_all_unconfirmed_and_no_alt_is_rejected(self):
        """Multiple explicit targets, all unconfirmed, no alternatives → REJECTED."""
        from core.capability_aware_routing_default import (
            apply_capability_aware_default,
            CapabilityRoutingOutcome,
        )

        decision = apply_capability_aware_default(
            tool_name="take_photo",
            explicit_targets=["dev-a", "dev-b"],
            routable_executors=[],
            required_capabilities=["camera"],
        )

        assert decision.outcome == CapabilityRoutingOutcome.CAPABILITY_REJECTED
        assert decision.recommended_targets == []


# ===========================================================================
# E) Capability mismatch REROUTE
# ===========================================================================


class TestCapabilityMismatchReroute:
    """Explicit device_id with wrong capabilities but capable alternatives
    exist → CAPABILITY_REROUTED (not a warning, and not the explicit device)."""

    def test_explicit_target_not_in_graph_reroutes_to_capable_alternative(self):
        """When an explicit target is not in the capability graph but there
        IS a capable alternative, routing redirects to the capable device."""
        from core.capability_aware_routing_default import (
            apply_capability_aware_default,
            CapabilityRoutingOutcome,
        )

        # Only 'capable-device' is in the graph (not 'bad-device')
        executors = [_FakeExecutor("capable-device")]
        decision = apply_capability_aware_default(
            tool_name="take_photo",
            explicit_targets=["bad-device"],
            routable_executors=executors,
            required_capabilities=["camera"],
        )

        assert decision.outcome == CapabilityRoutingOutcome.CAPABILITY_REROUTED
        assert "capable-device" in decision.recommended_targets
        assert "bad-device" not in decision.recommended_targets
        assert decision.original_explicit_targets == ["bad-device"]

    def test_reroute_does_not_include_original_bad_target(self):
        """Rerouted targets must NOT include the original incapable device."""
        from core.capability_aware_routing_default import (
            apply_capability_aware_default,
        )

        executors = [_FakeExecutor("alt-device")]
        decision = apply_capability_aware_default(
            tool_name="take_photo",
            explicit_targets=["incapable-device"],
            routable_executors=executors,
            required_capabilities=["camera"],
        )

        assert "incapable-device" not in decision.recommended_targets
        assert "alt-device" in decision.recommended_targets

    def test_reroute_reason_mentions_reroute(self):
        """The reroute reason must clearly indicate rerouting for observability."""
        from core.capability_aware_routing_default import (
            apply_capability_aware_default,
        )

        executors = [_FakeExecutor("good-device")]
        decision = apply_capability_aware_default(
            tool_name="take_photo",
            explicit_targets=["bad-device"],
            routable_executors=executors,
            required_capabilities=["camera"],
        )

        assert "rerouted" in decision.reason.lower()


# ===========================================================================
# F) Explicit override in exception path
# ===========================================================================


class TestExplicitOverrideExceptionPath:
    """Explicit device_id with no inferrable capabilities → EXPLICIT_OVERRIDE
    (audited exception path, not the default main path)."""

    def test_unknown_tool_with_explicit_target_is_audited_override(self):
        """When the tool/command has no capability entry and the caller
        supplies an explicit device_id, the outcome is EXPLICIT_OVERRIDE —
        indicating the request is on the exception path, not the default."""
        from core.capability_aware_routing_default import (
            apply_capability_aware_default,
            CapabilityRoutingOutcome,
        )

        decision = apply_capability_aware_default(
            tool_name="unknown_unregistered_command_xyz",
            explicit_targets=["some-device"],
            routable_executors=[_FakeExecutor("some-device")],
        )

        assert decision.outcome == CapabilityRoutingOutcome.EXPLICIT_OVERRIDE
        assert decision.is_explicit_override is True
        assert "some-device" in decision.recommended_targets

    def test_explicit_override_is_not_the_default_main_path(self):
        """The EXPLICIT_OVERRIDE outcome must be flagged so callers can
        distinguish it from the default capability-matched path."""
        from core.capability_aware_routing_default import (
            apply_capability_aware_default,
            CapabilityRoutingOutcome,
        )

        decision = apply_capability_aware_default(
            tool_name="totally_unknown_xyz",
            explicit_targets=["dev-forced"],
            routable_executors=[],
        )

        assert decision.outcome == CapabilityRoutingOutcome.EXPLICIT_OVERRIDE
        assert decision.is_explicit_override is True
        # But routing still proceeds — override is audited, not blocked
        assert "dev-forced" in decision.recommended_targets

    def test_no_explicit_target_no_requirements_is_noop(self):
        """No explicit target, no inferrable capabilities → NO_REQUIREMENTS
        (backward-compatible no-op; gate is inactive)."""
        from core.capability_aware_routing_default import (
            apply_capability_aware_default,
            CapabilityRoutingOutcome,
        )

        decision = apply_capability_aware_default(
            tool_name="completely_unknown_tool_zzz",
            explicit_targets=[],
            routable_executors=[_FakeExecutor("some-device")],
        )

        assert decision.outcome == CapabilityRoutingOutcome.NO_REQUIREMENTS
        assert decision.is_explicit_override is False


# ===========================================================================
# G) Capability inference from tool_name
# ===========================================================================


class TestCapabilityInferenceFromToolName:
    """Capability inference from tool_name activates the gate automatically."""

    def test_take_photo_infers_camera(self):
        """'take_photo' must infer 'camera' capability."""
        from core.capability_aware_routing_default import infer_dispatch_capabilities

        caps = infer_dispatch_capabilities("take_photo")
        assert "camera" in caps

    def test_screen_click_infers_screen_and_touch(self):
        """'screen_click' must infer 'screen' and 'touch' capabilities."""
        from core.capability_aware_routing_default import infer_dispatch_capabilities

        caps = infer_dispatch_capabilities("screen_click")
        assert "screen" in caps
        assert "touch" in caps

    def test_unknown_command_infers_empty(self):
        """Unknown commands return an empty list (not an error)."""
        from core.capability_aware_routing_default import infer_dispatch_capabilities

        caps = infer_dispatch_capabilities("totally_unknown_xyz")
        assert caps == []

    def test_empty_tool_name_infers_empty(self):
        """Empty tool_name returns empty list (backward compatible)."""
        from core.capability_aware_routing_default import infer_dispatch_capabilities

        assert infer_dispatch_capabilities("") == []

    def test_inference_without_explicit_required_caps_activates_gate(self):
        """When required_capabilities is absent but tool_name is recognisable,
        inference activates the gate and produces a non-trivial outcome."""
        from core.capability_aware_routing_default import (
            apply_capability_aware_default,
            CapabilityRoutingOutcome,
        )

        # take_photo infers ['camera']; 'camera-device' is in the graph.
        executors = [_FakeExecutor("camera-device")]
        decision = apply_capability_aware_default(
            tool_name="take_photo",
            explicit_targets=[],
            routable_executors=executors,
            required_capabilities=None,  # explicitly NOT provided
        )

        assert decision.outcome == CapabilityRoutingOutcome.CAPABILITY_MATCHED
        assert "camera" in decision.applied_capabilities
        assert decision.inferred_capabilities == ["camera"]


# ===========================================================================
# H) mainline_routing_enforcement new sentinels
# ===========================================================================


class TestMainlineRoutingEnforcementNewSentinels:
    """New policy sentinels in mainline_routing_enforcement are importable."""

    def test_explicit_route_is_exception_path_sentinel_importable(self):
        from core.mainline_routing_enforcement import EXPLICIT_ROUTE_IS_EXCEPTION_PATH

        assert EXPLICIT_ROUTE_IS_EXCEPTION_PATH
        assert "exception" in EXPLICIT_ROUTE_IS_EXCEPTION_PATH.lower()

    def test_capability_aware_routing_is_default_mainline_sentinel_importable(self):
        from core.mainline_routing_enforcement import (
            CAPABILITY_AWARE_ROUTING_IS_DEFAULT_MAINLINE,
        )

        assert CAPABILITY_AWARE_ROUTING_IS_DEFAULT_MAINLINE
        assert "default" in CAPABILITY_AWARE_ROUTING_IS_DEFAULT_MAINLINE.lower()
        assert "capability" in CAPABILITY_AWARE_ROUTING_IS_DEFAULT_MAINLINE.lower()

    def test_explicit_route_policy_mentions_exception_path(self):
        from core.mainline_routing_enforcement import EXPLICIT_ROUTE_IS_EXCEPTION_PATH

        assert "exception" in EXPLICIT_ROUTE_IS_EXCEPTION_PATH.lower()
        assert "device_id" in EXPLICIT_ROUTE_IS_EXCEPTION_PATH.lower()

    def test_default_mainline_policy_mentions_capability_graph(self):
        from core.mainline_routing_enforcement import (
            CAPABILITY_AWARE_ROUTING_IS_DEFAULT_MAINLINE,
        )

        assert "capability" in CAPABILITY_AWARE_ROUTING_IS_DEFAULT_MAINLINE.lower()


# ===========================================================================
# I) apply_capability_aware_default — all outcome paths produce correct records
# ===========================================================================


class TestApplyCapabilityAwareDefaultOutcomes:
    """apply_capability_aware_default produces correct CapabilityAwareRoutingDecision
    for every possible outcome path."""

    def test_to_dict_serialisable(self):
        """CapabilityAwareRoutingDecision.to_dict() returns a plain dict."""
        from core.capability_aware_routing_default import (
            apply_capability_aware_default,
        )

        decision = apply_capability_aware_default(
            tool_name="take_photo",
            explicit_targets=["dev-1"],
            routable_executors=[_FakeExecutor("dev-1")],
            required_capabilities=["camera"],
        )

        d = decision.to_dict()
        assert isinstance(d, dict)
        assert "outcome" in d
        assert "recommended_targets" in d
        assert "applied_capabilities" in d
        assert "original_explicit_targets" in d

    def test_all_outcomes_have_non_empty_reason(self):
        """Every outcome path produces a non-empty reason string for
        observability."""
        from core.capability_aware_routing_default import (
            apply_capability_aware_default,
            CapabilityRoutingOutcome,
        )

        cases = [
            # (tool, targets, executors, required_caps, expected_outcome)
            (
                "take_photo",
                ["dev-1"],
                [_FakeExecutor("dev-1")],
                ["camera"],
                CapabilityRoutingOutcome.CAPABILITY_MATCHED,
            ),
            (
                "take_photo",
                ["bad"],
                [_FakeExecutor("alt")],
                ["camera"],
                CapabilityRoutingOutcome.CAPABILITY_REROUTED,
            ),
            (
                "take_photo",
                ["bad"],
                [],
                ["camera"],
                CapabilityRoutingOutcome.CAPABILITY_REJECTED,
            ),
            (
                "unknown_xyz",
                ["dev-1"],
                [],
                None,
                CapabilityRoutingOutcome.EXPLICIT_OVERRIDE,
            ),
            (
                "unknown_xyz",
                [],
                [],
                None,
                CapabilityRoutingOutcome.NO_REQUIREMENTS,
            ),
        ]

        for tool, targets, execs, req_caps, expected_outcome in cases:
            decision = apply_capability_aware_default(
                tool_name=tool,
                explicit_targets=targets,
                routable_executors=execs,
                required_capabilities=req_caps,
            )
            assert decision.outcome == expected_outcome, (
                f"Expected {expected_outcome} but got {decision.outcome} "
                f"for tool={tool!r} targets={targets!r}"
            )
            assert decision.reason, (
                f"Reason must not be empty for outcome {decision.outcome} "
                f"(tool={tool!r})"
            )

    def test_capability_matched_no_explicit_target_sets_applied_caps(self):
        """The CAPABILITY_MATCHED path (no explicit target) populates
        applied_capabilities from inference so the decision is auditable."""
        from core.capability_aware_routing_default import (
            apply_capability_aware_default,
            CapabilityRoutingOutcome,
        )

        decision = apply_capability_aware_default(
            tool_name="take_photo",
            explicit_targets=[],
            routable_executors=[_FakeExecutor("cam-dev")],
        )

        assert decision.outcome == CapabilityRoutingOutcome.CAPABILITY_MATCHED
        assert decision.applied_capabilities  # must not be empty

    def test_capability_rerouted_preserves_original_explicit_targets(self):
        """After rerouting, original_explicit_targets records the caller's
        original request for audit purposes."""
        from core.capability_aware_routing_default import (
            apply_capability_aware_default,
            CapabilityRoutingOutcome,
        )

        decision = apply_capability_aware_default(
            tool_name="take_photo",
            explicit_targets=["original-incapable"],
            routable_executors=[_FakeExecutor("capable-alt")],
            required_capabilities=["camera"],
        )

        assert decision.outcome == CapabilityRoutingOutcome.CAPABILITY_REROUTED
        assert decision.original_explicit_targets == ["original-incapable"]
        assert "capable-alt" in decision.recommended_targets
