#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr15_task_semantics.py
====================================

Tests for PR-15: Task Semantics & Step Classes.

Coverage
--------
A) StepKind enum
   - all expected kind values present
   - string values are stable
   - enum is str subclass
   - STEP_KIND_ORDER contains all kinds
   - SIDE_EFFECTFUL_KINDS and READONLY_KINDS are disjoint for core kinds
   - step_kind_description returns non-empty strings
   - is_side_effectful_kind correct for execute, rollback, notify, unknown
   - is_readonly_kind correct for perceive, analyze, decide
   - coerce_step_kind handles StepKind input, string, unknown/None

B) StepSemanticPolicy dataclass
   - construction with explicit fields
   - to_dict() produces stable JSON-serialisable dict
   - from_dict() reconstruction
   - frozen / immutable
   - round-trip fidelity
   - __repr__ smoke test
   - DEFAULT_SAFE_STEP_POLICY has expected values
   - DEFAULT_EXECUTE_STEP_POLICY has expected values

C) build_policy_for_kind factory
   - perceive → not side_effectful, skippable
   - execute → side_effectful, not skippable, manifest visible
   - rollback → side_effectful, not skippable, preferred_recovery_posture=abort_task
   - notify → side_effectful, skippable, cross_device_allowed
   - confirm → requires_confirmation
   - observe_remote → not side_effectful, cross_device_allowed
   - unknown → conservative (side_effectful, not skippable)
   - overrides (cross_device_allowed, failure_skippable, requires_confirmation) respected
   - policy_reason override respected

D) ClassifiedStep dataclass
   - construction with all fields
   - to_dict() serialisation
   - from_dict() reconstruction
   - frozen / immutable
   - __repr__ smoke test

E) TaskSemanticSummary dataclass
   - construction with all fields
   - to_dict() serialisation
   - from_dict() reconstruction
   - round-trip fidelity
   - EMPTY_SEMANTIC_SUMMARY constant
   - total_steps derived property
   - is_fully_resolved derived property (unresolved_count=0 and >0)
   - frozen / immutable
   - __repr__ smoke test

F) attach_semantic_summary_to_projection helper
   - adds "task_semantics" key to projection dict
   - original dict not modified
   - non-dict input handled gracefully
   - existing fields preserved

G) get_semantic_hints helper
   - empty summary → correct hint dict
   - populated summary → all keys present with correct values
   - primary_visible_step_count and observability_highlight_count correct

H) resolve_step_kind resolver
   - explicit metadata step_kind wins
   - tool_name "screenshot" → perceive / source_hint="tool_name"
   - tool_name "click" → execute
   - tool_name "rollback" → rollback
   - tool_name "notify" → notify
   - tool_name "confirm" → confirm
   - description "rollback the action" → rollback
   - description "take a screenshot" → perceive
   - mirrored_observation routing policy → observe_remote
   - observe_only execution policy band → perceive
   - unknown tool_name and description → unknown / source_hint="fallback"
   - None inputs → unknown / fallback
   - case-insensitive tool_name matching

I) resolve_step_policy resolver
   - returns StepSemanticPolicy with correct kind
   - execution_policy cross_device_allowed respected
   - execution_policy requires_confirmation respected
   - routing_policy is_cross_device respected
   - None inputs degrade gracefully

J) classify_task_node
   - dict node with node_id and tool_name
   - dict node with description
   - dict node with explicit metadata step_kind
   - None node → ClassifiedStep with UNKNOWN kind
   - object-like node (dataclass stub)

K) classify_task_envelope
   - dict envelope with task_id and tool_name
   - dict envelope with metadata description
   - None envelope → ClassifiedStep with UNKNOWN kind
   - Pydantic-like object envelope

L) build_semantic_summary_from_graph
   - None graph → EMPTY_SEMANTIC_SUMMARY
   - graph with _nodes dict of node-like objects
   - graph with side-effectful and readonly nodes
   - trace_id / graph_id propagated

M) build_semantic_summary_from_envelopes
   - empty list → EMPTY_SEMANTIC_SUMMARY
   - list with mixed-kind envelopes
   - has_side_effectful_steps and has_cross_device_steps correct
   - task_id / trace_id propagated

N) build_semantic_summary_from_dicts
   - empty list → EMPTY_SEMANTIC_SUMMARY
   - list of step dicts with various tool_names
   - None entries gracefully skipped
   - unresolved_count correct for unknown/unresolvable dicts

O) Public API surface (__init__ re-exports)
   - all documented names importable from core.task_semantics
"""

from __future__ import annotations

import dataclasses
import pytest

# ---------------------------------------------------------------------------
# Module-level imports
# ---------------------------------------------------------------------------

from core.task_semantics.step_kind import (
    StepKind,
    STEP_KIND_ORDER,
    SIDE_EFFECTFUL_KINDS,
    READONLY_KINDS,
    step_kind_description,
    is_side_effectful_kind,
    is_readonly_kind,
    coerce_step_kind,
)
from core.task_semantics.step_policy import (
    StepSemanticPolicy,
    DEFAULT_SAFE_STEP_POLICY,
    DEFAULT_EXECUTE_STEP_POLICY,
    build_policy_for_kind,
)
from core.task_semantics.task_semantic_summary import (
    ClassifiedStep,
    TaskSemanticSummary,
    EMPTY_SEMANTIC_SUMMARY,
    attach_semantic_summary_to_projection,
    get_semantic_hints,
)
from core.task_semantics.step_resolver import (
    resolve_step_kind,
    resolve_step_policy,
    classify_task_node,
    classify_task_envelope,
    build_semantic_summary_from_graph,
    build_semantic_summary_from_envelopes,
    build_semantic_summary_from_dicts,
)
from core.task_semantics import (
    StepKind as _StepKindPublic,
    StepSemanticPolicy as _PolicyPublic,
    TaskSemanticSummary as _SummaryPublic,
    build_semantic_summary_from_graph as _graph_public,
)


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _FakeNode:
    """Minimal TaskNode-like stub for tests that need an object (not a dict)."""

    node_id: str = ""
    description: str = ""
    metadata: dict = dataclasses.field(default_factory=dict)
    tool_name: str = ""


# ===========================================================================
# A) StepKind enum
# ===========================================================================

class TestStepKind:

    def test_all_expected_values_present(self):
        expected = {
            "perceive", "analyze", "decide", "execute",
            "confirm", "notify", "rollback", "observe_remote", "unknown",
        }
        actual = {k.value for k in StepKind}
        assert expected == actual

    def test_string_values_are_stable(self):
        assert StepKind.PERCEIVE.value == "perceive"
        assert StepKind.EXECUTE.value == "execute"
        assert StepKind.ROLLBACK.value == "rollback"
        assert StepKind.OBSERVE_REMOTE.value == "observe_remote"
        assert StepKind.UNKNOWN.value == "unknown"

    def test_enum_is_str_subclass(self):
        assert isinstance(StepKind.PERCEIVE, str)
        assert StepKind.PERCEIVE == "perceive"

    def test_step_kind_order_contains_all(self):
        assert set(STEP_KIND_ORDER) == set(StepKind)

    def test_side_effectful_and_readonly_disjoint_for_core(self):
        # Core deterministic kinds should not appear in both sets
        overlap = SIDE_EFFECTFUL_KINDS & READONLY_KINDS
        assert len(overlap) == 0

    def test_step_kind_description_non_empty(self):
        for kind in StepKind:
            desc = step_kind_description(kind)
            assert isinstance(desc, str)
            assert len(desc) > 0

    def test_is_side_effectful_kind(self):
        assert is_side_effectful_kind(StepKind.EXECUTE) is True
        assert is_side_effectful_kind(StepKind.ROLLBACK) is True
        assert is_side_effectful_kind(StepKind.NOTIFY) is True
        assert is_side_effectful_kind(StepKind.UNKNOWN) is True
        assert is_side_effectful_kind(StepKind.PERCEIVE) is False
        assert is_side_effectful_kind(StepKind.ANALYZE) is False

    def test_is_readonly_kind(self):
        assert is_readonly_kind(StepKind.PERCEIVE) is True
        assert is_readonly_kind(StepKind.ANALYZE) is True
        assert is_readonly_kind(StepKind.DECIDE) is True
        assert is_readonly_kind(StepKind.EXECUTE) is False
        assert is_readonly_kind(StepKind.ROLLBACK) is False

    def test_coerce_step_kind_passthrough(self):
        assert coerce_step_kind(StepKind.EXECUTE) is StepKind.EXECUTE

    def test_coerce_step_kind_from_string(self):
        assert coerce_step_kind("perceive") == StepKind.PERCEIVE
        assert coerce_step_kind("EXECUTE") == StepKind.EXECUTE
        assert coerce_step_kind("  Rollback  ") == StepKind.ROLLBACK

    def test_coerce_step_kind_unknown_fallback(self):
        assert coerce_step_kind(None) == StepKind.UNKNOWN
        assert coerce_step_kind("not_a_real_kind") == StepKind.UNKNOWN
        assert coerce_step_kind(42) == StepKind.UNKNOWN


# ===========================================================================
# B) StepSemanticPolicy
# ===========================================================================

class TestStepSemanticPolicy:

    def _make_policy(self, **kwargs) -> StepSemanticPolicy:
        defaults = dict(
            step_kind=StepKind.EXECUTE,
            side_effectful=True,
            requires_confirmation=False,
            cross_device_allowed=False,
            failure_skippable=False,
            should_surface_in_manifest=True,
            should_emit_observability_highlight=True,
            preferred_recovery_posture="retry_same_device",
            policy_reason="test policy",
        )
        defaults.update(kwargs)
        return StepSemanticPolicy(**defaults)

    def test_construction(self):
        p = self._make_policy()
        assert p.step_kind == StepKind.EXECUTE
        assert p.side_effectful is True
        assert p.failure_skippable is False

    def test_to_dict_stable(self):
        p = self._make_policy()
        d = p.to_dict()
        assert d["step_kind"] == "execute"
        assert d["side_effectful"] is True
        assert d["preferred_recovery_posture"] == "retry_same_device"
        assert isinstance(d, dict)

    def test_from_dict_reconstruction(self):
        p = self._make_policy()
        d = p.to_dict()
        p2 = StepSemanticPolicy.from_dict(d)
        assert p2.step_kind == p.step_kind
        assert p2.side_effectful == p.side_effectful
        assert p2.preferred_recovery_posture == p.preferred_recovery_posture

    def test_frozen(self):
        p = self._make_policy()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
            p.side_effectful = False  # type: ignore[misc]

    def test_round_trip(self):
        p = self._make_policy(cross_device_allowed=True, failure_skippable=True)
        p2 = StepSemanticPolicy.from_dict(p.to_dict())
        assert p2 == p

    def test_repr(self):
        p = self._make_policy()
        r = repr(p)
        assert "execute" in r
        assert "StepSemanticPolicy" in r

    def test_default_safe_policy(self):
        assert DEFAULT_SAFE_STEP_POLICY.step_kind == StepKind.PERCEIVE
        assert DEFAULT_SAFE_STEP_POLICY.side_effectful is False
        assert DEFAULT_SAFE_STEP_POLICY.failure_skippable is True

    def test_default_execute_policy(self):
        assert DEFAULT_EXECUTE_STEP_POLICY.step_kind == StepKind.EXECUTE
        assert DEFAULT_EXECUTE_STEP_POLICY.side_effectful is True
        assert DEFAULT_EXECUTE_STEP_POLICY.failure_skippable is False
        assert DEFAULT_EXECUTE_STEP_POLICY.should_emit_observability_highlight is True


# ===========================================================================
# C) build_policy_for_kind factory
# ===========================================================================

class TestBuildPolicyForKind:

    def test_perceive_defaults(self):
        p = build_policy_for_kind(StepKind.PERCEIVE)
        assert p.side_effectful is False
        assert p.failure_skippable is True
        assert p.should_surface_in_manifest is False

    def test_execute_defaults(self):
        p = build_policy_for_kind(StepKind.EXECUTE)
        assert p.side_effectful is True
        assert p.failure_skippable is False
        assert p.should_surface_in_manifest is True
        assert p.should_emit_observability_highlight is True
        assert p.preferred_recovery_posture == "retry_same_device"

    def test_rollback_defaults(self):
        p = build_policy_for_kind(StepKind.ROLLBACK)
        assert p.side_effectful is True
        assert p.failure_skippable is False
        assert p.preferred_recovery_posture == "abort_task"

    def test_notify_defaults(self):
        p = build_policy_for_kind(StepKind.NOTIFY)
        assert p.side_effectful is True
        assert p.failure_skippable is True
        assert p.cross_device_allowed is True
        assert p.preferred_recovery_posture == "skip_optional_branch"

    def test_confirm_defaults(self):
        p = build_policy_for_kind(StepKind.CONFIRM)
        assert p.requires_confirmation is True
        assert p.failure_skippable is False
        assert p.preferred_recovery_posture == "require_confirmation"

    def test_observe_remote_defaults(self):
        p = build_policy_for_kind(StepKind.OBSERVE_REMOTE)
        assert p.side_effectful is False
        assert p.cross_device_allowed is True
        assert p.failure_skippable is True

    def test_unknown_conservative(self):
        p = build_policy_for_kind(StepKind.UNKNOWN)
        assert p.side_effectful is True
        assert p.failure_skippable is False

    def test_cross_device_override(self):
        p = build_policy_for_kind(StepKind.PERCEIVE, cross_device_allowed=True)
        assert p.cross_device_allowed is True

    def test_failure_skippable_override(self):
        p = build_policy_for_kind(StepKind.EXECUTE, failure_skippable=True)
        assert p.failure_skippable is True

    def test_requires_confirmation_override(self):
        p = build_policy_for_kind(StepKind.EXECUTE, requires_confirmation=True)
        assert p.requires_confirmation is True

    def test_policy_reason_override(self):
        p = build_policy_for_kind(StepKind.PERCEIVE, policy_reason="custom reason")
        assert p.policy_reason == "custom reason"

    def test_string_kind_coerced(self):
        p = build_policy_for_kind("execute")
        assert p.step_kind == StepKind.EXECUTE


# ===========================================================================
# D) ClassifiedStep
# ===========================================================================

class TestClassifiedStep:

    def _make_step(self) -> ClassifiedStep:
        policy = build_policy_for_kind(StepKind.EXECUTE)
        return ClassifiedStep(
            step_id="n1",
            step_label="click submit",
            step_kind=StepKind.EXECUTE,
            policy=policy,
            source_hint="tool_name",
        )

    def test_construction(self):
        step = self._make_step()
        assert step.step_id == "n1"
        assert step.step_kind == StepKind.EXECUTE
        assert step.source_hint == "tool_name"

    def test_to_dict(self):
        step = self._make_step()
        d = step.to_dict()
        assert d["step_id"] == "n1"
        assert d["step_kind"] == "execute"
        assert d["source_hint"] == "tool_name"
        assert isinstance(d["policy"], dict)

    def test_from_dict(self):
        step = self._make_step()
        d = step.to_dict()
        step2 = ClassifiedStep.from_dict(d)
        assert step2.step_id == step.step_id
        assert step2.step_kind == step.step_kind

    def test_frozen(self):
        step = self._make_step()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
            step.step_id = "changed"  # type: ignore[misc]

    def test_repr(self):
        step = self._make_step()
        r = repr(step)
        assert "ClassifiedStep" in r
        assert "execute" in r


# ===========================================================================
# E) TaskSemanticSummary
# ===========================================================================

class TestTaskSemanticSummary:

    def _make_summary(self, **kwargs) -> TaskSemanticSummary:
        steps = [
            ClassifiedStep(
                step_id="n1",
                step_label="screenshot",
                step_kind=StepKind.PERCEIVE,
                policy=build_policy_for_kind(StepKind.PERCEIVE),
                source_hint="tool_name",
            ),
            ClassifiedStep(
                step_id="n2",
                step_label="click",
                step_kind=StepKind.EXECUTE,
                policy=build_policy_for_kind(StepKind.EXECUTE),
                source_hint="tool_name",
            ),
        ]
        defaults = dict(
            task_id="task_123",
            trace_id="trace_abc",
            runtime_session_id="sess_xyz",
            classified_steps=steps,
            has_side_effectful_steps=True,
            has_cross_device_steps=False,
            has_confirmation_required_steps=False,
            has_rollback_steps=False,
            primary_visible_steps=["n2"],
            observability_highlight_steps=["n2"],
            unresolved_count=0,
        )
        defaults.update(kwargs)
        return TaskSemanticSummary(**defaults)

    def test_construction(self):
        s = self._make_summary()
        assert s.task_id == "task_123"
        assert s.total_steps == 2

    def test_to_dict(self):
        s = self._make_summary()
        d = s.to_dict()
        assert d["task_id"] == "task_123"
        assert d["total_steps"] == 2
        assert isinstance(d["classified_steps"], list)
        assert d["has_side_effectful_steps"] is True
        assert d["is_fully_resolved"] is True

    def test_from_dict_reconstruction(self):
        s = self._make_summary()
        d = s.to_dict()
        s2 = TaskSemanticSummary.from_dict(d)
        assert s2.task_id == s.task_id
        assert s2.total_steps == s.total_steps

    def test_round_trip(self):
        s = self._make_summary()
        s2 = TaskSemanticSummary.from_dict(s.to_dict())
        assert s2.task_id == s.task_id
        assert s2.has_side_effectful_steps == s.has_side_effectful_steps

    def test_empty_summary_constant(self):
        assert EMPTY_SEMANTIC_SUMMARY.total_steps == 0
        assert EMPTY_SEMANTIC_SUMMARY.is_fully_resolved is True
        assert EMPTY_SEMANTIC_SUMMARY.has_side_effectful_steps is False

    def test_total_steps_property(self):
        s = self._make_summary()
        assert s.total_steps == 2

    def test_is_fully_resolved_true(self):
        s = self._make_summary(unresolved_count=0)
        assert s.is_fully_resolved is True

    def test_is_fully_resolved_false(self):
        s = self._make_summary(unresolved_count=1)
        assert s.is_fully_resolved is False

    def test_frozen(self):
        s = self._make_summary()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
            s.task_id = "changed"  # type: ignore[misc]

    def test_repr(self):
        s = self._make_summary()
        r = repr(s)
        assert "TaskSemanticSummary" in r


# ===========================================================================
# F) attach_semantic_summary_to_projection
# ===========================================================================

class TestAttachSemanticSummaryToProjection:

    def test_adds_task_semantics_key(self):
        proj = {"tri_state_phase": "manifest"}
        result = attach_semantic_summary_to_projection(proj, EMPTY_SEMANTIC_SUMMARY)
        assert "task_semantics" in result

    def test_original_not_mutated(self):
        proj = {"tri_state_phase": "manifest"}
        attach_semantic_summary_to_projection(proj, EMPTY_SEMANTIC_SUMMARY)
        assert "task_semantics" not in proj

    def test_non_dict_input(self):
        result = attach_semantic_summary_to_projection(None, EMPTY_SEMANTIC_SUMMARY)
        assert "task_semantics" in result

    def test_existing_fields_preserved(self):
        proj = {"tri_state_phase": "manifest", "foo": "bar"}
        result = attach_semantic_summary_to_projection(proj, EMPTY_SEMANTIC_SUMMARY)
        assert result["tri_state_phase"] == "manifest"
        assert result["foo"] == "bar"


# ===========================================================================
# G) get_semantic_hints
# ===========================================================================

class TestGetSemanticHints:

    def test_empty_summary_hints(self):
        hints = get_semantic_hints(EMPTY_SEMANTIC_SUMMARY)
        assert hints["total_steps"] == 0
        assert hints["has_side_effectful_steps"] is False
        assert hints["is_fully_resolved"] is True
        assert hints["primary_visible_step_count"] == 0

    def test_all_hint_keys_present(self):
        hints = get_semantic_hints(EMPTY_SEMANTIC_SUMMARY)
        expected_keys = {
            "total_steps", "unresolved_count", "is_fully_resolved",
            "has_side_effectful_steps", "has_cross_device_steps",
            "has_confirmation_required_steps", "has_rollback_steps",
            "primary_visible_step_count", "observability_highlight_count",
            "task_id", "trace_id",
        }
        assert expected_keys.issubset(set(hints.keys()))

    def test_populated_summary_hints(self):
        s = TaskSemanticSummary(
            task_id="t1",
            trace_id="trace1",
            classified_steps=[],
            has_side_effectful_steps=True,
            has_cross_device_steps=True,
            primary_visible_steps=["n1", "n2"],
            observability_highlight_steps=["n2"],
        )
        hints = get_semantic_hints(s)
        assert hints["has_side_effectful_steps"] is True
        assert hints["has_cross_device_steps"] is True
        assert hints["primary_visible_step_count"] == 2
        assert hints["observability_highlight_count"] == 1


# ===========================================================================
# H) resolve_step_kind resolver
# ===========================================================================

class TestResolveStepKind:

    def test_explicit_metadata_wins(self):
        kind, source = resolve_step_kind(
            tool_name="click",
            metadata={"step_kind": "rollback"},
        )
        assert kind == StepKind.ROLLBACK
        assert source == "explicit"

    def test_tool_name_screenshot(self):
        kind, source = resolve_step_kind(tool_name="screenshot")
        assert kind == StepKind.PERCEIVE
        assert source == "tool_name"

    def test_tool_name_click(self):
        kind, source = resolve_step_kind(tool_name="click")
        assert kind == StepKind.EXECUTE
        assert source == "tool_name"

    def test_tool_name_rollback(self):
        kind, source = resolve_step_kind(tool_name="rollback")
        assert kind == StepKind.ROLLBACK
        assert source == "tool_name"

    def test_tool_name_notify(self):
        kind, source = resolve_step_kind(tool_name="notify")
        assert kind == StepKind.NOTIFY
        assert source == "tool_name"

    def test_tool_name_confirm(self):
        kind, source = resolve_step_kind(tool_name="confirm")
        assert kind == StepKind.CONFIRM
        assert source == "tool_name"

    def test_description_rollback(self):
        kind, source = resolve_step_kind(description="rollback the previous action")
        assert kind == StepKind.ROLLBACK
        assert source == "description"

    def test_description_screenshot(self):
        kind, source = resolve_step_kind(description="take a screenshot of the screen")
        assert kind == StepKind.PERCEIVE
        assert source == "description"

    def test_routing_policy_mirrored_observation(self):
        routing = {"posture": "mirrored_observation"}
        kind, source = resolve_step_kind(routing_policy=routing)
        assert kind == StepKind.OBSERVE_REMOTE
        assert source == "routing_policy"

    def test_execution_policy_observe_only(self):
        ep = {"policy_band": "observe_only"}
        kind, source = resolve_step_kind(execution_policy=ep)
        assert kind == StepKind.PERCEIVE
        assert source == "execution_policy"

    def test_no_inputs_fallback(self):
        kind, source = resolve_step_kind()
        assert kind == StepKind.UNKNOWN
        assert source == "fallback"

    def test_none_inputs_fallback(self):
        kind, source = resolve_step_kind(tool_name=None, description=None)
        assert kind == StepKind.UNKNOWN
        assert source == "fallback"

    def test_case_insensitive_tool_name(self):
        kind, source = resolve_step_kind(tool_name="SCREENSHOT")
        assert kind == StepKind.PERCEIVE

    def test_unknown_tool_name_fallback(self):
        kind, source = resolve_step_kind(tool_name="xyzzy_unknown_action_99")
        assert kind == StepKind.UNKNOWN
        assert source == "fallback"


# ===========================================================================
# I) resolve_step_policy resolver
# ===========================================================================

class TestResolveStepPolicy:

    def test_returns_step_semantic_policy(self):
        p = resolve_step_policy(tool_name="screenshot")
        assert isinstance(p, StepSemanticPolicy)
        assert p.step_kind == StepKind.PERCEIVE

    def test_execution_policy_cross_device_respected(self):
        ep = {"cross_device_allowed": True, "requires_confirmation": False}
        p = resolve_step_policy(tool_name="click", execution_policy=ep)
        assert p.cross_device_allowed is True

    def test_execution_policy_confirmation_respected(self):
        ep = {"cross_device_allowed": False, "requires_confirmation": True}
        p = resolve_step_policy(tool_name="click", execution_policy=ep)
        assert p.requires_confirmation is True

    def test_routing_policy_cross_device_respected(self):
        routing = {"is_cross_device": True, "posture": "local_then_expand"}
        p = resolve_step_policy(tool_name="screenshot", routing_policy=routing)
        assert p.cross_device_allowed is True

    def test_none_inputs_degrade_gracefully(self):
        p = resolve_step_policy()
        assert isinstance(p, StepSemanticPolicy)
        assert p.step_kind == StepKind.UNKNOWN


# ===========================================================================
# J) classify_task_node
# ===========================================================================

class TestClassifyTaskNode:

    def test_dict_node_with_tool_name(self):
        node = {"node_id": "n1", "tool_name": "screenshot"}
        step = classify_task_node(node)
        assert step.step_id == "n1"
        assert step.step_kind == StepKind.PERCEIVE
        assert step.source_hint == "tool_name"

    def test_dict_node_with_description(self):
        node = {"node_id": "n2", "description": "click the submit button"}
        step = classify_task_node(node)
        assert step.step_kind == StepKind.EXECUTE
        assert step.source_hint == "description"

    def test_dict_node_explicit_metadata(self):
        node = {"node_id": "n3", "metadata": {"step_kind": "rollback"}}
        step = classify_task_node(node)
        assert step.step_kind == StepKind.ROLLBACK
        assert step.source_hint == "explicit"

    def test_none_node(self):
        step = classify_task_node(None)
        assert step.step_kind == StepKind.UNKNOWN

    def test_object_like_node(self):
        step = classify_task_node(_FakeNode(node_id="n4", description="take screenshot"))
        assert step.step_id == "n4"
        assert step.step_kind == StepKind.PERCEIVE


# ===========================================================================
# K) classify_task_envelope
# ===========================================================================

class TestClassifyTaskEnvelope:

    def test_dict_envelope_with_tool_name(self):
        env = {"task_id": "t1", "tool_name": "click"}
        step = classify_task_envelope(env)
        assert step.step_id == "t1"
        assert step.step_kind == StepKind.EXECUTE

    def test_dict_envelope_with_metadata_description(self):
        env = {
            "task_id": "t2",
            "tool_name": "",
            "metadata": {"description": "rollback the changes"},
        }
        step = classify_task_envelope(env)
        assert step.step_kind == StepKind.ROLLBACK

    def test_none_envelope(self):
        step = classify_task_envelope(None)
        assert step.step_kind == StepKind.UNKNOWN

    def test_object_envelope(self):
        @dataclasses.dataclass
        class FakeEnvelope:
            task_id: str = "t3"
            tool_name: str = "notify"
            metadata: dict = dataclasses.field(default_factory=dict)

        step = classify_task_envelope(FakeEnvelope())
        assert step.step_id == "t3"
        assert step.step_kind == StepKind.NOTIFY

# ===========================================================================
# L) build_semantic_summary_from_graph
# ===========================================================================

class TestBuildSemanticSummaryFromGraph:

    def test_none_graph(self):
        result = build_semantic_summary_from_graph(None)
        assert result is EMPTY_SEMANTIC_SUMMARY

    def test_graph_with_nodes_dict(self):
        class FakeGraph:
            graph_id = "g1"
            trace_id = "trace_g"
            runtime_session_id = "sess_g"
            _nodes = {
                "n1": _FakeNode(node_id="n1", tool_name="screenshot"),
                "n2": _FakeNode(node_id="n2", tool_name="click"),
            }

        result = build_semantic_summary_from_graph(FakeGraph())
        assert result.total_steps == 2
        assert result.trace_id == "trace_g"
        assert result.has_side_effectful_steps is True

    def test_graph_readonly_nodes_only(self):
        class FakeGraph:
            graph_id = "g2"
            trace_id = ""
            runtime_session_id = ""
            _nodes = {
                "n1": _FakeNode(node_id="n1", tool_name="screenshot"),
                "n2": _FakeNode(node_id="n2", tool_name="analyze"),
            }

        result = build_semantic_summary_from_graph(FakeGraph())
        assert result.has_side_effectful_steps is False

    def test_graph_id_propagated(self):
        class FakeGraph:
            graph_id = "mygraph"
            trace_id = "mytrace"
            runtime_session_id = ""
            _nodes = {}

        result = build_semantic_summary_from_graph(FakeGraph())
        assert result.task_id == "mygraph"
        assert result.trace_id == "mytrace"


# ===========================================================================
# M) build_semantic_summary_from_envelopes
# ===========================================================================

class TestBuildSemanticSummaryFromEnvelopes:

    def test_empty_list(self):
        result = build_semantic_summary_from_envelopes([])
        assert result is EMPTY_SEMANTIC_SUMMARY

    def test_mixed_kind_envelopes(self):
        envs = [
            {"task_id": "t1", "trace_id": "tr1", "tool_name": "screenshot"},
            {"task_id": "t2", "trace_id": "tr1", "tool_name": "click"},
        ]
        result = build_semantic_summary_from_envelopes(envs)
        assert result.total_steps == 2
        assert result.has_side_effectful_steps is True

    def test_task_id_propagated(self):
        envs = [{"task_id": "top_task", "tool_name": "screenshot"}]
        result = build_semantic_summary_from_envelopes(envs)
        assert result.task_id == "top_task"

    def test_cross_device_steps_detected(self):
        envs = [{"task_id": "t1", "tool_name": "observe_remote"}]
        result = build_semantic_summary_from_envelopes(envs)
        assert result.has_cross_device_steps is True

    def test_none_entries_skipped(self):
        envs = [None, {"task_id": "t1", "tool_name": "screenshot"}, None]
        result = build_semantic_summary_from_envelopes(envs)
        assert result.total_steps == 1


# ===========================================================================
# N) build_semantic_summary_from_dicts
# ===========================================================================

class TestBuildSemanticSummaryFromDicts:

    def test_empty_list(self):
        result = build_semantic_summary_from_dicts([])
        assert result is EMPTY_SEMANTIC_SUMMARY

    def test_various_tool_names(self):
        steps = [
            {"node_id": "n1", "tool_name": "screenshot"},
            {"node_id": "n2", "tool_name": "click"},
            {"node_id": "n3", "tool_name": "notify"},
        ]
        result = build_semantic_summary_from_dicts(steps)
        assert result.total_steps == 3
        assert result.has_side_effectful_steps is True

    def test_none_entries_skipped(self):
        steps = [None, {"node_id": "n1", "tool_name": "screenshot"}, None]
        result = build_semantic_summary_from_dicts(steps)
        assert result.total_steps == 1

    def test_unresolved_count(self):
        steps = [
            {"node_id": "n1", "tool_name": "some_totally_unknown_tool_xyz"},
            {"node_id": "n2"},  # no tool_name or description
        ]
        result = build_semantic_summary_from_dicts(steps)
        assert result.unresolved_count == 2

    def test_rollback_steps_detected(self):
        steps = [
            {"node_id": "n1", "tool_name": "rollback"},
        ]
        result = build_semantic_summary_from_dicts(steps)
        assert result.has_rollback_steps is True


# ===========================================================================
# O) Public API surface
# ===========================================================================

class TestPublicAPISurface:

    def test_all_documented_names_importable(self):
        import core.task_semantics as ts

        expected_names = [
            "StepKind",
            "STEP_KIND_ORDER",
            "SIDE_EFFECTFUL_KINDS",
            "READONLY_KINDS",
            "step_kind_description",
            "is_side_effectful_kind",
            "is_readonly_kind",
            "coerce_step_kind",
            "StepSemanticPolicy",
            "DEFAULT_SAFE_STEP_POLICY",
            "DEFAULT_EXECUTE_STEP_POLICY",
            "build_policy_for_kind",
            "ClassifiedStep",
            "TaskSemanticSummary",
            "EMPTY_SEMANTIC_SUMMARY",
            "attach_semantic_summary_to_projection",
            "get_semantic_hints",
            "resolve_step_kind",
            "resolve_step_policy",
            "classify_task_node",
            "classify_task_envelope",
            "build_semantic_summary_from_graph",
            "build_semantic_summary_from_envelopes",
            "build_semantic_summary_from_dicts",
        ]
        for name in expected_names:
            assert hasattr(ts, name), f"Missing public name: {name!r}"

    def test_public_reexports_are_same_objects(self):
        assert _StepKindPublic is StepKind
        assert _PolicyPublic is StepSemanticPolicy
        assert _SummaryPublic is TaskSemanticSummary
        assert _graph_public is build_semantic_summary_from_graph
