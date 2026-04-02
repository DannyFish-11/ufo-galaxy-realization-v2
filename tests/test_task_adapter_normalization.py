#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_task_adapter_normalization.py
==========================================

PR-A: Canonical Task & Execution Spine — task adapter normalization tests.

Validates that TaskAdapterLayer correctly normalizes all input origins
into CanonicalTask instances.

Test groups
-----------
  A)  Authority sentinels importable and correct values.
  B)  AdaptationRecord construction and to_dict().
  C)  TaskAdapterLayer.adapt() — CanonicalTask passthrough.
  D)  TaskAdapterLayer.adapt() — TaskEnvelope fast path.
  E)  TaskAdapterLayer.adapt() — API request dict normalization.
  F)  TaskAdapterLayer.adapt() — AI intent dict normalization.
  G)  TaskAdapterLayer.adapt() — workflow step dict normalization.
  H)  TaskAdapterLayer.adapt() — orchestrator task dict normalization.
  I)  TaskAdapterLayer.adapt() — device command dict normalization.
  J)  TaskAdapterLayer.adapt() — MCP tool call dict normalization.
  K)  TaskAdapterLayer.adapt() — skill invocation dict normalization.
  L)  TaskAdapterLayer.adapt() — minimal empty dict normalization.
  M)  adapt_to_canonical_task() top-level helper.
  N)  Adaptation log populated after adapt().
  O)  reset_adaptation_log() clears log.
  P)  get_adaptation_log() returns list.
  Q)  Passthrough sets was_passthrough=True in log.
  R)  Non-passthrough sets was_passthrough=False in log.
  S)  Task IDs / trace IDs propagated from input dict.
  T)  Session IDs propagated from input dict.
  U)  Targets extracted from various dict keys.
  V)  Args extracted from various dict keys.
  W)  All public names appear in __all__.
"""

from __future__ import annotations

import pytest

from core.task_adapter import (
    TASK_ADAPTER_AUTHORITY,
    TASK_ADAPTER_NORMALIZATION_POLICY,
    AdaptationRecord,
    TaskAdapterLayer,
    adapt_to_canonical_task,
    get_adaptation_log,
    reset_adaptation_log,
)
from core.canonical_task import (
    CanonicalTask,
    TaskOrigin,
    build_canonical_task,
    reset_canonical_task_runtime,
)
import core.task_adapter as _mod


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture(autouse=True)
def reset_state():
    reset_canonical_task_runtime()
    reset_adaptation_log()
    yield
    reset_canonical_task_runtime()
    reset_adaptation_log()


# ===========================================================================
# A) Authority sentinels
# ===========================================================================

def test_A1_authority_importable():
    assert TASK_ADAPTER_AUTHORITY is not None


def test_A2_authority_contains_keyword():
    assert "TASK_ADAPTER" in TASK_ADAPTER_AUTHORITY


def test_A3_normalization_policy_non_empty():
    assert isinstance(TASK_ADAPTER_NORMALIZATION_POLICY, str)
    assert len(TASK_ADAPTER_NORMALIZATION_POLICY) > 0


def test_A4_policy_mentions_canonical_task():
    assert "CanonicalTask" in TASK_ADAPTER_NORMALIZATION_POLICY


# ===========================================================================
# B) AdaptationRecord
# ===========================================================================

def test_B1_record_defaults():
    rec = AdaptationRecord()
    assert rec.task_id == ""
    assert rec.trace_id == ""
    assert rec.origin == "unknown"
    assert rec.tool == ""
    assert rec.targets == []
    assert rec.was_passthrough is False


def test_B2_record_to_dict_keys():
    rec = AdaptationRecord()
    d = rec.to_dict()
    for k in ("record_id", "task_id", "trace_id", "origin", "tool", "targets", "was_passthrough"):
        assert k in d


# ===========================================================================
# C) Passthrough — CanonicalTask
# ===========================================================================

def test_C1_canonical_task_passthrough():
    adapter = TaskAdapterLayer()
    task = build_canonical_task(register=False)
    result = adapter.adapt(task, origin=TaskOrigin.API_REQUEST)
    assert result is task


def test_C2_passthrough_returns_same_task_id():
    adapter = TaskAdapterLayer()
    task = build_canonical_task(register=False)
    result = adapter.adapt(task)
    assert result.task_id == task.task_id


# ===========================================================================
# D) TaskEnvelope fast path
# ===========================================================================

def test_D1_task_envelope_fast_path():
    try:
        from core.schemas.task_envelope import TaskEnvelope
    except ImportError:
        pytest.skip("TaskEnvelope not available")
    adapter = TaskAdapterLayer()
    env = TaskEnvelope(tool_name="screenshot", targets=["dev1"])
    result = adapter.adapt(env, origin=TaskOrigin.API_REQUEST)
    assert isinstance(result, CanonicalTask)


def test_D2_task_envelope_preserves_task_id():
    try:
        from core.schemas.task_envelope import TaskEnvelope
    except ImportError:
        pytest.skip("TaskEnvelope not available")
    adapter = TaskAdapterLayer()
    env = TaskEnvelope(task_id="task_test_001", tool_name="screenshot")
    result = adapter.adapt(env, origin=TaskOrigin.API_REQUEST)
    assert result.task_id == "task_test_001"


# ===========================================================================
# E) API request normalization
# ===========================================================================

def test_E1_api_request_dict():
    adapter = TaskAdapterLayer()
    payload = {"action": "screenshot", "target_device_id": "dev_01"}
    task = adapter.adapt(payload, origin=TaskOrigin.API_REQUEST)
    assert isinstance(task, CanonicalTask)
    assert task.intent.origin == TaskOrigin.API_REQUEST


def test_E2_api_request_tool_extracted():
    adapter = TaskAdapterLayer()
    payload = {"tool_name": "ping", "args": {"host": "8.8.8.8"}}
    task = adapter.adapt(payload, origin=TaskOrigin.API_REQUEST)
    assert task.execution.tool == "ping"


def test_E3_api_request_args_extracted():
    adapter = TaskAdapterLayer()
    payload = {"tool_name": "ping", "args": {"host": "8.8.8.8"}}
    task = adapter.adapt(payload, origin=TaskOrigin.API_REQUEST)
    assert task.execution.args.get("host") == "8.8.8.8"


# ===========================================================================
# F) AI intent normalization
# ===========================================================================

def test_F1_ai_intent_dict():
    adapter = TaskAdapterLayer()
    payload = {"action": "open_app", "goal": "open spotify"}
    task = adapter.adapt(payload, origin=TaskOrigin.AI_INTENT)
    assert isinstance(task, CanonicalTask)
    assert task.intent.origin == TaskOrigin.AI_INTENT


def test_F2_ai_intent_goal_preserved():
    adapter = TaskAdapterLayer()
    payload = {"action": "open_app", "goal": "open spotify"}
    task = adapter.adapt(payload, origin=TaskOrigin.AI_INTENT)
    assert task.intent.goal == "open spotify"


# ===========================================================================
# G) Workflow step normalization
# ===========================================================================

def test_G1_workflow_step_dict():
    adapter = TaskAdapterLayer()
    payload = {"task_type": "data_fetch", "description": "fetch sensor data"}
    task = adapter.adapt(payload, origin=TaskOrigin.WORKFLOW_STEP)
    assert isinstance(task, CanonicalTask)
    assert task.intent.origin == TaskOrigin.WORKFLOW_STEP


# ===========================================================================
# H) Orchestrator task normalization
# ===========================================================================

def test_H1_orchestrator_task_dict():
    adapter = TaskAdapterLayer()
    payload = {"command": "deploy", "device_id": "node_01"}
    task = adapter.adapt(payload, origin=TaskOrigin.ORCHESTRATOR_TASK)
    assert isinstance(task, CanonicalTask)
    assert task.intent.origin == TaskOrigin.ORCHESTRATOR_TASK


# ===========================================================================
# I) Device command normalization
# ===========================================================================

def test_I1_device_command_dict():
    adapter = TaskAdapterLayer()
    payload = {"action": "tap", "target_device": "phone_01", "args": {"x": 100, "y": 200}}
    task = adapter.adapt(payload, origin=TaskOrigin.DEVICE_COMMAND)
    assert isinstance(task, CanonicalTask)
    assert task.intent.origin == TaskOrigin.DEVICE_COMMAND


def test_I2_device_command_target_extracted():
    adapter = TaskAdapterLayer()
    payload = {"action": "tap", "target_device": "phone_01"}
    task = adapter.adapt(payload, origin=TaskOrigin.DEVICE_COMMAND)
    assert "phone_01" in task.routing.selected_targets


# ===========================================================================
# J) MCP tool call normalization
# ===========================================================================

def test_J1_mcp_tool_call_dict():
    adapter = TaskAdapterLayer()
    payload = {"tool": "search_web", "params": {"query": "weather"}}
    task = adapter.adapt(payload, origin=TaskOrigin.MCP_TOOL_CALL)
    assert isinstance(task, CanonicalTask)
    assert task.intent.origin == TaskOrigin.MCP_TOOL_CALL


def test_J2_mcp_tool_extracted():
    adapter = TaskAdapterLayer()
    payload = {"tool": "search_web", "params": {"query": "weather"}}
    task = adapter.adapt(payload, origin=TaskOrigin.MCP_TOOL_CALL)
    assert task.execution.tool == "search_web"


# ===========================================================================
# K) Skill invocation normalization
# ===========================================================================

def test_K1_skill_invocation_dict():
    adapter = TaskAdapterLayer()
    payload = {"skill": "translate_text", "args": {"text": "hello", "lang": "zh"}}
    task = adapter.adapt(payload, origin=TaskOrigin.SKILL_INVOCATION)
    assert isinstance(task, CanonicalTask)
    assert task.intent.origin == TaskOrigin.SKILL_INVOCATION


def test_K2_skill_name_extracted():
    adapter = TaskAdapterLayer()
    payload = {"skill": "translate_text", "args": {"text": "hello"}}
    task = adapter.adapt(payload, origin=TaskOrigin.SKILL_INVOCATION)
    assert task.execution.tool == "translate_text"


# ===========================================================================
# L) Minimal empty dict
# ===========================================================================

def test_L1_empty_dict():
    adapter = TaskAdapterLayer()
    task = adapter.adapt({}, origin=TaskOrigin.UNKNOWN)
    assert isinstance(task, CanonicalTask)
    assert task.task_id.startswith("task_")


# ===========================================================================
# M) adapt_to_canonical_task() top-level helper
# ===========================================================================

def test_M1_helper_function():
    payload = {"tool_name": "ping", "targets": ["dev1"]}
    task = adapt_to_canonical_task(payload, origin=TaskOrigin.API_REQUEST)
    assert isinstance(task, CanonicalTask)


def test_M2_helper_preserves_origin():
    task = adapt_to_canonical_task({}, origin=TaskOrigin.SCHEDULER)
    assert task.intent.origin == TaskOrigin.SCHEDULER


# ===========================================================================
# N) Adaptation log populated
# ===========================================================================

def test_N1_log_populated_after_adapt():
    reset_adaptation_log()
    adapt_to_canonical_task({"tool_name": "x"})
    log = get_adaptation_log()
    assert len(log) >= 1


# ===========================================================================
# O) reset_adaptation_log()
# ===========================================================================

def test_O1_reset_clears_log():
    adapt_to_canonical_task({"tool_name": "x"})
    reset_adaptation_log()
    assert get_adaptation_log() == []


# ===========================================================================
# P) get_adaptation_log() returns list
# ===========================================================================

def test_P1_returns_list():
    assert isinstance(get_adaptation_log(), list)


# ===========================================================================
# Q) Passthrough sets was_passthrough=True
# ===========================================================================

def test_Q1_passthrough_flag_true():
    reset_adaptation_log()
    task = build_canonical_task(register=False)
    adapt_to_canonical_task(task)
    log = get_adaptation_log()
    assert any(r.was_passthrough for r in log)


# ===========================================================================
# R) Non-passthrough sets was_passthrough=False
# ===========================================================================

def test_R1_non_passthrough_flag_false():
    reset_adaptation_log()
    adapt_to_canonical_task({"tool_name": "screenshot"}, origin=TaskOrigin.API_REQUEST)
    log = get_adaptation_log()
    assert any(not r.was_passthrough for r in log)


# ===========================================================================
# S) Task ID / trace ID propagated from dict
# ===========================================================================

def test_S1_task_id_from_dict():
    task = adapt_to_canonical_task(
        {"task_id": "task_custom_001", "tool_name": "ping"},
        origin=TaskOrigin.API_REQUEST,
    )
    assert task.task_id == "task_custom_001"


def test_S2_trace_id_from_dict():
    task = adapt_to_canonical_task(
        {"trace_id": "trace_abc", "tool_name": "ping"},
        origin=TaskOrigin.API_REQUEST,
    )
    assert task.trace_id == "trace_abc"


# ===========================================================================
# T) Session ID propagated
# ===========================================================================

def test_T1_session_id_from_kwarg():
    task = adapt_to_canonical_task({}, session_id="sess_123")
    assert task.session_id == "sess_123"


def test_T2_session_id_from_dict():
    task = adapt_to_canonical_task({"session_id": "sess_dict_456"})
    assert task.session_id == "sess_dict_456"


# ===========================================================================
# U) Targets extracted from various keys
# ===========================================================================

def test_U1_targets_from_targets_key():
    task = adapt_to_canonical_task({"tool_name": "x", "targets": ["dev1", "dev2"]})
    assert "dev1" in task.routing.selected_targets
    assert "dev2" in task.routing.selected_targets


def test_U2_targets_from_target_device_id():
    task = adapt_to_canonical_task({"tool_name": "x", "target_device_id": "android_01"})
    assert "android_01" in task.routing.selected_targets


def test_U3_targets_from_device_id():
    task = adapt_to_canonical_task({"tool_name": "x", "device_id": "tablet_01"})
    assert "tablet_01" in task.routing.selected_targets


# ===========================================================================
# V) Args extracted from various keys
# ===========================================================================

def test_V1_args_from_args_key():
    task = adapt_to_canonical_task({"tool_name": "x", "args": {"a": 1}})
    assert task.execution.args.get("a") == 1


def test_V2_args_from_payload_key():
    task = adapt_to_canonical_task({"tool_name": "x", "payload": {"b": 2}})
    assert task.execution.args.get("b") == 2


def test_V3_args_from_params_key():
    task = adapt_to_canonical_task({"tool_name": "x", "params": {"c": 3}})
    assert task.execution.args.get("c") == 3


# ===========================================================================
# W) __all__ completeness
# ===========================================================================

def test_W1_all_exports_importable():
    for name in _mod.__all__:
        assert hasattr(_mod, name), f"{name} missing from module"
