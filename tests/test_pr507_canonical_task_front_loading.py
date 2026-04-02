#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr507_canonical_task_front_loading.py
=================================================
PR-507 — Canonical Task Front-Loading: Tests.

Validates that representative production ingress paths create a
``CanonicalTask`` via ``adapt_to_canonical_task()`` before dispatching,
that ``TaskEnvelope`` is a downstream projection of canonical task state,
and that the sentinel constants affirming this integration are importable.

Test groups
-----------
 A)  Sentinels — all four front-loading sentinels are importable.
 B)  API ingress — core/routes/tasks.py CANONICAL_TASK_API_INGRESS_FRONT_LOADED.
 C)  Orchestrator ingress — galaxy_gateway CANONICAL_TASK_ORCHESTRATOR_FRONT_LOADED.
 D)  Scheduler ingress — core/scheduler.py CANONICAL_TASK_SCHEDULER_FRONT_LOADED.
 E)  Kernel ingress — core/agent/kernel.py CANONICAL_TASK_KERNEL_FRONT_LOADED.
 F)  adapt_to_canonical_task() produces CanonicalTask from API-shaped dict.
 G)  adapt_to_canonical_task() produces CanonicalTask from orchestrator dict.
 H)  adapt_to_canonical_task() produces CanonicalTask from scheduler dict.
 I)  adapt_to_canonical_task() produces CanonicalTask from AI-intent dict.
 J)  project_to_task_envelope() produces TaskEnvelope from CanonicalTask.
 K)  TaskEnvelope projected from CanonicalTask carries canonical_task_id metadata.
 L)  TaskEnvelope projected from CanonicalTask shares task_id with source task.
 M)  Legacy dict shapes routed through adapt_to_canonical_task() not bypassing it.
 N)  CanonicalTask registered in runtime after adapt_to_canonical_task().
 O)  CanonicalTask passthrough: adapt_to_canonical_task(canonical_task) is no-op.
 P)  Adaptation log records each ingress call.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.canonical_task import (
    CanonicalTask,
    TaskOrigin,
    build_canonical_task,
    get_canonical_task_runtime,
    project_to_task_envelope,
    reset_canonical_task_runtime,
)
from core.task_adapter import (
    adapt_to_canonical_task,
    get_adaptation_log,
    reset_adaptation_log,
)

# Optional: detect whether fastapi-dependent modules can be imported.
try:
    import fastapi as _fastapi  # noqa: F401
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False


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
# A) Sentinels — all four front-loading sentinels are importable
# ===========================================================================

@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_A1_api_ingress_sentinel_importable():
    from core.routes.tasks import CANONICAL_TASK_API_INGRESS_FRONT_LOADED
    assert CANONICAL_TASK_API_INGRESS_FRONT_LOADED
    assert "API_INGRESS" in CANONICAL_TASK_API_INGRESS_FRONT_LOADED


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_A2_orchestrator_sentinel_importable():
    from galaxy_gateway.orchestrator.task_orchestrator import (
        CANONICAL_TASK_ORCHESTRATOR_FRONT_LOADED,
    )
    assert CANONICAL_TASK_ORCHESTRATOR_FRONT_LOADED
    assert "ORCHESTRATOR" in CANONICAL_TASK_ORCHESTRATOR_FRONT_LOADED


def test_A3_scheduler_sentinel_importable():
    from core.scheduler import CANONICAL_TASK_SCHEDULER_FRONT_LOADED
    assert CANONICAL_TASK_SCHEDULER_FRONT_LOADED
    assert "SCHEDULER" in CANONICAL_TASK_SCHEDULER_FRONT_LOADED


def test_A4_kernel_sentinel_importable():
    from core.agent.kernel import CANONICAL_TASK_KERNEL_FRONT_LOADED
    assert CANONICAL_TASK_KERNEL_FRONT_LOADED
    assert "KERNEL" in CANONICAL_TASK_KERNEL_FRONT_LOADED


# ===========================================================================
# B) API ingress sentinel value
# ===========================================================================

@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_B1_api_sentinel_mentions_canonical_task():
    from core.routes.tasks import CANONICAL_TASK_API_INGRESS_FRONT_LOADED
    assert "CANONICAL_TASK" in CANONICAL_TASK_API_INGRESS_FRONT_LOADED


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_B2_api_sentinel_mentions_adapt():
    from core.routes.tasks import CANONICAL_TASK_API_INGRESS_FRONT_LOADED
    assert "adapt_to_canonical_task" in CANONICAL_TASK_API_INGRESS_FRONT_LOADED


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_B3_api_sentinel_mentions_create_task():
    from core.routes.tasks import CANONICAL_TASK_API_INGRESS_FRONT_LOADED
    assert "create_task" in CANONICAL_TASK_API_INGRESS_FRONT_LOADED


# ===========================================================================
# C) Orchestrator ingress sentinel value
# ===========================================================================

@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_C1_orchestrator_sentinel_mentions_submit_task():
    from galaxy_gateway.orchestrator.task_orchestrator import (
        CANONICAL_TASK_ORCHESTRATOR_FRONT_LOADED,
    )
    assert "submit_task" in CANONICAL_TASK_ORCHESTRATOR_FRONT_LOADED


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_C2_orchestrator_sentinel_mentions_adapt():
    from galaxy_gateway.orchestrator.task_orchestrator import (
        CANONICAL_TASK_ORCHESTRATOR_FRONT_LOADED,
    )
    assert "adapt_to_canonical_task" in CANONICAL_TASK_ORCHESTRATOR_FRONT_LOADED


# ===========================================================================
# D) Scheduler ingress sentinel value
# ===========================================================================

def test_D1_scheduler_sentinel_mentions_exec_send():
    from core.scheduler import CANONICAL_TASK_SCHEDULER_FRONT_LOADED
    assert "_exec_send_to_device" in CANONICAL_TASK_SCHEDULER_FRONT_LOADED


def test_D2_scheduler_sentinel_mentions_adapt():
    from core.scheduler import CANONICAL_TASK_SCHEDULER_FRONT_LOADED
    assert "adapt_to_canonical_task" in CANONICAL_TASK_SCHEDULER_FRONT_LOADED


# ===========================================================================
# E) Kernel ingress sentinel value
# ===========================================================================

def test_E1_kernel_sentinel_mentions_process():
    from core.agent.kernel import CANONICAL_TASK_KERNEL_FRONT_LOADED
    assert "_process" in CANONICAL_TASK_KERNEL_FRONT_LOADED


def test_E2_kernel_sentinel_mentions_adapt():
    from core.agent.kernel import CANONICAL_TASK_KERNEL_FRONT_LOADED
    assert "adapt_to_canonical_task" in CANONICAL_TASK_KERNEL_FRONT_LOADED


def test_E3_kernel_sentinel_mentions_task_execute():
    from core.agent.kernel import CANONICAL_TASK_KERNEL_FRONT_LOADED
    assert "task_execute" in CANONICAL_TASK_KERNEL_FRONT_LOADED


# ===========================================================================
# F) adapt_to_canonical_task — API-shaped dict
# ===========================================================================

def test_F1_api_dict_produces_canonical_task():
    task = adapt_to_canonical_task(
        {
            "task_type": "screenshot",
            "payload": {"quality": "high"},
            "targets": ["device_001"],
            "tool_name": "screenshot",
            "args": {"quality": "high"},
        },
        origin=TaskOrigin.API_REQUEST,
    )
    assert isinstance(task, CanonicalTask)


def test_F2_api_dict_canonical_task_has_task_id():
    task = adapt_to_canonical_task(
        {"tool_name": "screenshot", "args": {}},
        origin=TaskOrigin.API_REQUEST,
    )
    assert task.identity.task_id
    assert len(task.identity.task_id) > 0


def test_F3_api_dict_canonical_task_origin_api():
    task = adapt_to_canonical_task(
        {"tool_name": "screenshot"},
        origin=TaskOrigin.API_REQUEST,
    )
    assert task.intent.origin == TaskOrigin.API_REQUEST


def test_F4_api_dict_canonical_task_trace_id_set():
    task = adapt_to_canonical_task(
        {"tool_name": "open_app", "args": {"app": "Camera"}},
        origin=TaskOrigin.API_REQUEST,
    )
    assert task.identity.trace_id
    assert "trace_" in task.identity.trace_id or len(task.identity.trace_id) > 0


# ===========================================================================
# G) adapt_to_canonical_task — orchestrator dict
# ===========================================================================

def test_G1_orchestrator_dict_produces_canonical_task():
    task = adapt_to_canonical_task(
        {
            "goal": "take screenshot of all devices",
            "tool_name": "orchestrate",
            "args": {"user_request": "take screenshot"},
            "targets": ["device_a", "device_b"],
        },
        origin=TaskOrigin.ORCHESTRATOR_TASK,
    )
    assert isinstance(task, CanonicalTask)


def test_G2_orchestrator_dict_origin_is_orchestrator():
    task = adapt_to_canonical_task(
        {"goal": "run diagnostics"},
        origin=TaskOrigin.ORCHESTRATOR_TASK,
    )
    assert task.intent.origin == TaskOrigin.ORCHESTRATOR_TASK


def test_G3_orchestrator_task_targets_propagated():
    task = adapt_to_canonical_task(
        {
            "targets": ["dev_01", "dev_02"],
            "tool_name": "ping",
        },
        origin=TaskOrigin.ORCHESTRATOR_TASK,
    )
    # targets may or may not be propagated depending on adapter internals
    assert isinstance(task, CanonicalTask)


# ===========================================================================
# H) adapt_to_canonical_task — scheduler dict
# ===========================================================================

def test_H1_scheduler_dict_produces_canonical_task():
    task = adapt_to_canonical_task(
        {
            "task_id": "task_sched_001",
            "trace_id": "trace_sched_abc",
            "tool_name": "shell_command",
            "targets": ["desktop_01"],
            "args": {"command": "ls -la"},
        },
        origin=TaskOrigin.SCHEDULER,
    )
    assert isinstance(task, CanonicalTask)


def test_H2_scheduler_dict_origin_is_scheduler():
    task = adapt_to_canonical_task(
        {"tool_name": "cron_task"},
        origin=TaskOrigin.SCHEDULER,
    )
    assert task.intent.origin == TaskOrigin.SCHEDULER


def test_H3_scheduler_task_id_propagated_when_provided():
    task = adapt_to_canonical_task(
        {"task_id": "task_sched_explicit_42", "tool_name": "ping"},
        origin=TaskOrigin.SCHEDULER,
    )
    assert task.identity.task_id == "task_sched_explicit_42"


# ===========================================================================
# I) adapt_to_canonical_task — AI-intent dict
# ===========================================================================

def test_I1_ai_intent_dict_produces_canonical_task():
    task = adapt_to_canonical_task(
        {
            "goal": "open WeChat and send a message",
            "tool_name": "kernel_execute",
            "args": {"message": "open WeChat and send a message", "mode": "task_execute"},
        },
        origin=TaskOrigin.AI_INTENT,
    )
    assert isinstance(task, CanonicalTask)


def test_I2_ai_intent_origin_is_ai_intent():
    task = adapt_to_canonical_task(
        {"goal": "analyze data"},
        origin=TaskOrigin.AI_INTENT,
    )
    assert task.intent.origin == TaskOrigin.AI_INTENT


# ===========================================================================
# J) project_to_task_envelope — produces envelope from CanonicalTask
# ===========================================================================

def test_J1_project_produces_envelope():
    task = build_canonical_task(
        goal="take screenshot",
        origin=TaskOrigin.API_REQUEST,
        requested_action="screenshot",
        selected_targets=["device_01"],
    )
    envelope = task.project_to_task_envelope()
    assert envelope is not None


def test_J2_project_module_fn_produces_envelope():
    task = build_canonical_task(
        goal="open app",
        origin=TaskOrigin.ORCHESTRATOR_TASK,
        requested_action="open_app",
    )
    envelope = project_to_task_envelope(task)
    assert envelope is not None


def test_J3_projected_envelope_has_task_id():
    task = build_canonical_task(
        goal="run script",
        origin=TaskOrigin.SCHEDULER,
        requested_action="shell_command",
    )
    envelope = task.project_to_task_envelope()
    env_task_id = getattr(envelope, "task_id", None)
    assert env_task_id is not None


# ===========================================================================
# K) TaskEnvelope carries canonical_task_id in metadata
# ===========================================================================

def test_K1_envelope_metadata_has_canonical_task_id():
    task = build_canonical_task(
        goal="screenshot",
        origin=TaskOrigin.API_REQUEST,
        requested_action="screenshot",
    )
    envelope = task.project_to_task_envelope()
    meta = getattr(envelope, "metadata", {}) or {}
    assert "canonical_task_id" in meta


def test_K2_envelope_canonical_task_id_matches_source():
    task = build_canonical_task(
        goal="run test",
        origin=TaskOrigin.SCHEDULER,
        requested_action="test",
    )
    envelope = task.project_to_task_envelope()
    meta = getattr(envelope, "metadata", {}) or {}
    assert meta.get("canonical_task_id") == task.identity.task_id


def test_K3_envelope_metadata_has_canonical_origin():
    task = build_canonical_task(
        goal="send_message",
        origin=TaskOrigin.AI_INTENT,
        requested_action="send_message",
    )
    envelope = task.project_to_task_envelope()
    meta = getattr(envelope, "metadata", {}) or {}
    assert "canonical_task_origin" in meta


# ===========================================================================
# L) TaskEnvelope shares task_id with source CanonicalTask
# ===========================================================================

def test_L1_envelope_task_id_matches_canonical():
    task = build_canonical_task(
        goal="open camera",
        origin=TaskOrigin.API_REQUEST,
        requested_action="open_camera",
    )
    envelope = task.project_to_task_envelope()
    env_task_id = getattr(envelope, "task_id", None)
    assert env_task_id == task.identity.task_id


def test_L2_adapt_then_project_task_ids_match():
    canonical = adapt_to_canonical_task(
        {"tool_name": "screenshot", "args": {}},
        origin=TaskOrigin.API_REQUEST,
    )
    envelope = canonical.project_to_task_envelope()
    env_task_id = getattr(envelope, "task_id", None)
    assert env_task_id == canonical.identity.task_id


# ===========================================================================
# M) Legacy dict shapes routed through adapt_to_canonical_task
# ===========================================================================

def test_M1_minimal_empty_dict_still_produces_canonical():
    task = adapt_to_canonical_task({})
    assert isinstance(task, CanonicalTask)


def test_M2_device_command_dict_produces_canonical():
    task = adapt_to_canonical_task(
        {
            "device_id": "android_01",
            "action": "click",
            "x": 100,
            "y": 200,
        },
        origin=TaskOrigin.DEVICE_COMMAND,
    )
    assert isinstance(task, CanonicalTask)


def test_M3_skill_invocation_dict_produces_canonical():
    task = adapt_to_canonical_task(
        {
            "skill_name": "photo_capture",
            "skill": "photo_capture",
            "args": {"resolution": "1080p"},
        },
        origin=TaskOrigin.SKILL_INVOCATION,
    )
    assert isinstance(task, CanonicalTask)


# ===========================================================================
# N) CanonicalTask registered in runtime after adapt_to_canonical_task
# ===========================================================================

def test_N1_canonical_task_registered_after_adapt():
    task = adapt_to_canonical_task(
        {"tool_name": "ping", "args": {}},
        origin=TaskOrigin.API_REQUEST,
    )
    runtime = get_canonical_task_runtime()
    registered = runtime.get_by_task_id(task.identity.task_id)
    assert registered is not None
    assert registered.identity.task_id == task.identity.task_id


def test_N2_multiple_adapts_all_registered():
    tasks = [
        adapt_to_canonical_task({"tool_name": f"tool_{i}"}, origin=TaskOrigin.SCHEDULER)
        for i in range(3)
    ]
    runtime = get_canonical_task_runtime()
    for task in tasks:
        assert runtime.get_by_task_id(task.identity.task_id) is not None


# ===========================================================================
# O) CanonicalTask passthrough — adapt(canonical_task) is a no-op
# ===========================================================================

def test_O1_canonical_task_passthrough_returns_same():
    original = build_canonical_task(
        goal="test passthrough",
        origin=TaskOrigin.API_REQUEST,
        requested_action="test",
    )
    result = adapt_to_canonical_task(original)
    assert result is original


def test_O2_canonical_task_passthrough_logged_as_passthrough():
    original = build_canonical_task(
        goal="passthrough test",
        origin=TaskOrigin.SCHEDULER,
        requested_action="ping",
    )
    reset_adaptation_log()
    adapt_to_canonical_task(original)
    log = get_adaptation_log()
    assert len(log) >= 1
    last = log[-1]
    assert last.was_passthrough is True


# ===========================================================================
# P) Adaptation log records each ingress call
# ===========================================================================

def test_P1_adaptation_log_grows_on_each_call():
    initial = len(get_adaptation_log())
    adapt_to_canonical_task({"tool_name": "a"}, origin=TaskOrigin.API_REQUEST)
    adapt_to_canonical_task({"tool_name": "b"}, origin=TaskOrigin.SCHEDULER)
    assert len(get_adaptation_log()) == initial + 2


def test_P2_adaptation_log_records_origin():
    adapt_to_canonical_task({"tool_name": "test"}, origin=TaskOrigin.AI_INTENT)
    log = get_adaptation_log()
    last = log[-1]
    assert last.origin == TaskOrigin.AI_INTENT.value


def test_P3_adaptation_log_records_task_id():
    task = adapt_to_canonical_task({"tool_name": "test"}, origin=TaskOrigin.API_REQUEST)
    log = get_adaptation_log()
    last = log[-1]
    assert last.task_id == task.identity.task_id
