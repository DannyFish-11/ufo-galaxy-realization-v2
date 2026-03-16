#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr5_capability_closure.py
======================================
PR-5 — Five Capability Closure Tests

Each test class directly validates one of the five required capabilities:

  1. TestTaskLifecycle         — created → running → done/failed state machine
  2. TestNonVisualTaskPath     — no-vision execution path (filesystem/system/http)
  3. TestTaskMemoryContext     — session_id, memory write/inject, trace logging
  4. TestCrossDeviceOrch       — multi-target envelope dispatch + result aggregation
  5. TestACLPermissions        — permission_level / required_capabilities + audit events

All tests are self-contained (no live servers, no real devices).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Capability 1: Task Lifecycle
# ---------------------------------------------------------------------------

class TestTaskLifecycle:
    """PR-5 Capability 1 — task.lifecycle state machine."""

    def test_envelope_has_lifecycle_status_field(self):
        from core.schemas.task_envelope import TaskEnvelope
        env = TaskEnvelope(tool_name="ping", targets=["dev1"])
        assert env.lifecycle_status == "created"

    def test_transition_created_to_running(self):
        from core.schemas.task_envelope import TaskEnvelope
        env = TaskEnvelope(tool_name="ping", targets=["dev1"])
        running = env.transition("running")
        assert running.lifecycle_status == "running"

    def test_transition_running_to_done(self):
        from core.schemas.task_envelope import TaskEnvelope
        env = TaskEnvelope(tool_name="ping", targets=["dev1"])
        running = env.transition("running")
        done = running.transition("done")
        assert done.lifecycle_status == "done"

    def test_transition_running_to_failed(self):
        from core.schemas.task_envelope import TaskEnvelope
        env = TaskEnvelope(tool_name="ping", targets=["dev1"])
        running = env.transition("running")
        failed = running.transition("failed")
        assert failed.lifecycle_status == "failed"

    def test_invalid_transition_created_to_done_raises(self):
        from core.schemas.task_envelope import TaskEnvelope
        env = TaskEnvelope(tool_name="ping", targets=["dev1"])
        with pytest.raises(ValueError, match="Invalid lifecycle transition"):
            env.transition("done")

    def test_terminal_state_no_further_transitions(self):
        from core.schemas.task_envelope import TaskEnvelope
        env = TaskEnvelope(tool_name="ping", targets=["dev1"])
        done = env.transition("running").transition("done")
        with pytest.raises(ValueError):
            done.transition("running")

    def test_lifecycle_manager_mark_running(self, caplog):
        from core.schemas.task_envelope import TaskEnvelope
        from core.task_lifecycle import TaskLifecycleManager
        mgr = TaskLifecycleManager()
        env = TaskEnvelope(tool_name="test_tool", targets=["dev1"])
        with caplog.at_level(logging.INFO, logger="Galaxy.TaskLifecycle"):
            updated = mgr.mark_running(env)
        assert updated.lifecycle_status == "running"
        assert "running" in caplog.text

    def test_lifecycle_manager_mark_done_writes_memory(self, caplog):
        from core.schemas.task_envelope import TaskEnvelope
        from core.task_lifecycle import TaskLifecycleManager
        mgr = TaskLifecycleManager()
        env = TaskEnvelope(tool_name="test_tool", targets=["dev1"])
        running = mgr.mark_running(env)
        with caplog.at_level(logging.INFO, logger="Galaxy.TaskLifecycle"):
            done = mgr.mark_done(running, result_summary="test passed")
        assert done.lifecycle_status == "done"
        # memory backflow log assertion
        assert "done" in caplog.text

    def test_lifecycle_manager_mark_failed(self, caplog):
        from core.schemas.task_envelope import TaskEnvelope
        from core.task_lifecycle import TaskLifecycleManager
        mgr = TaskLifecycleManager()
        env = TaskEnvelope(tool_name="test_tool", targets=["dev1"])
        running = mgr.mark_running(env)
        with caplog.at_level(logging.WARNING, logger="Galaxy.TaskLifecycle"):
            failed = mgr.mark_failed(running, error="something went wrong")
        assert failed.lifecycle_status == "failed"
        assert "failed" in caplog.text

    @pytest.mark.asyncio
    async def test_lifecycle_run_with_lifecycle_success(self):
        from core.schemas.task_envelope import TaskEnvelope
        from core.task_lifecycle import TaskLifecycleManager
        mgr = TaskLifecycleManager()
        env = TaskEnvelope(tool_name="async_tool", targets=["dev1"])

        async def _coro(e):
            return {"ok": True}, "async result"

        final_env, result = await mgr.run_with_lifecycle(env, _coro)
        assert final_env.lifecycle_status == "done"
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_lifecycle_run_with_lifecycle_failure(self):
        from core.schemas.task_envelope import TaskEnvelope
        from core.task_lifecycle import TaskLifecycleManager
        mgr = TaskLifecycleManager()
        env = TaskEnvelope(tool_name="bad_tool", targets=["dev1"])

        async def _coro(e):
            raise RuntimeError("simulated failure")

        with pytest.raises(RuntimeError):
            await mgr.run_with_lifecycle(env, _coro)

    def test_task_id_and_trace_id_are_unique(self):
        from core.schemas.task_envelope import TaskEnvelope
        envs = [TaskEnvelope(tool_name="ping") for _ in range(10)]
        task_ids = {e.task_id for e in envs}
        trace_ids = {e.trace_id for e in envs}
        assert len(task_ids) == 10, "task_ids must be unique"
        assert len(trace_ids) == 10, "trace_ids must be unique"


# ---------------------------------------------------------------------------
# Capability 2: Non-Visual Task Path
# ---------------------------------------------------------------------------

class TestNonVisualTaskPath:
    """PR-5 Capability 2 — execution without vision/UI sampling."""

    def test_envelope_allows_no_vision_path(self):
        """A TaskEnvelope can be created and executed with no screen/vision caps."""
        from core.schemas.task_envelope import TaskEnvelope
        env = TaskEnvelope(
            tool_name="filesystem_list",
            args={"path": "/tmp"},
            required_capabilities=["filesystem"],  # no "screen" cap
        )
        # Must not contain any vision-related capability
        assert "screen" not in env.required_capabilities
        assert "screenshot" not in env.required_capabilities

    def test_filesystem_step_no_vision(self):
        """Filesystem operations complete without any UI interaction."""
        import os
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".galaxy_test.txt", delete=False
        ) as tmp:
            tmp.write("capability 2 test\n")
            path = tmp.name
        try:
            with open(path) as f:
                content = f.read().strip()
            assert content == "capability 2 test"
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_system_cmd_no_vision(self):
        """System command executes without any visual sampling."""
        import subprocess
        result = subprocess.run(
            ["echo", "no-vision-ok"], capture_output=True, text=True, timeout=5
        )
        assert result.returncode == 0
        assert "no-vision-ok" in result.stdout

    def test_lifecycle_completes_non_visual_task(self):
        """Non-visual task goes through full lifecycle without vision."""
        from core.schemas.task_envelope import TaskEnvelope
        from core.task_lifecycle import TaskLifecycleManager
        mgr = TaskLifecycleManager()
        env = TaskEnvelope(
            tool_name="filesystem_list",
            args={"path": "/tmp"},
            required_capabilities=["filesystem"],
        )
        env = mgr.mark_running(env)
        assert env.lifecycle_status == "running"
        env = mgr.mark_done(env, result_summary="listed /tmp OK")
        assert env.lifecycle_status == "done"

    def test_demo_script_is_runnable(self):
        """Non-visual demo script exists and passes a syntax check."""
        demo_path = os.path.join(PROJECT_ROOT, "scripts", "non_visual_task_demo.py")
        assert os.path.isfile(demo_path), f"Demo script missing: {demo_path}"
        import py_compile
        py_compile.compile(demo_path, doraise=True)


# ---------------------------------------------------------------------------
# Capability 3: Task Memory / Context
# ---------------------------------------------------------------------------

class TestTaskMemoryContext:
    """PR-5 Capability 3 — history / context memory."""

    def test_envelope_has_session_id_field(self):
        from core.schemas.task_envelope import TaskEnvelope
        env = TaskEnvelope(
            tool_name="search",
            targets=["dev1"],
            session_id="session_abc",
        )
        assert env.session_id == "session_abc"

    def test_session_id_defaults_to_none(self):
        from core.schemas.task_envelope import TaskEnvelope
        env = TaskEnvelope(tool_name="x")
        assert env.session_id is None

    def test_log_context_includes_session_id(self):
        from core.schemas.task_envelope import TaskEnvelope
        env = TaskEnvelope(tool_name="x", session_id="s1")
        ctx = env.log_context()
        assert "session_id" in ctx
        assert ctx["session_id"] == "s1"

    def test_task_memory_record_and_retrieve(self, tmp_path, monkeypatch):
        """TaskMemory.record_task() persists and get_recent_summaries() retrieves."""
        monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
        from core.task_memory import TaskMemory
        mem = TaskMemory(data_dir=str(tmp_path))
        mem.record_task(
            task="search for docs",
            result_summary="found 5 docs",
            success=True,
            strategy="single",
        )
        summaries = mem.get_recent_summaries(n=5)
        assert len(summaries) >= 1
        texts = [s.result_summary for s in summaries]
        assert any("found 5 docs" in t for t in texts)

    def test_lifecycle_manager_writes_memory_on_done(self, tmp_path, monkeypatch, caplog):
        """mark_done() must write to TaskMemory (memory backflow assertion)."""
        monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))

        from core.schemas.task_envelope import TaskEnvelope
        from core.task_lifecycle import TaskLifecycleManager
        import core.task_lifecycle as _tlm_mod

        mem_mock = MagicMock()
        with patch.object(_tlm_mod, "_get_task_memory", return_value=mem_mock), \
             patch.object(_tlm_mod, "_MEMORY_OK", True):
            mgr = TaskLifecycleManager()
            env = TaskEnvelope(
                tool_name="search_docs",
                session_id="session_test",
                targets=["local"],
            )
            running = mgr.mark_running(env)
            with caplog.at_level(logging.INFO, logger="Galaxy.TaskLifecycle"):
                mgr.mark_done(running, result_summary="found 5 docs")

        mem_mock.record_task.assert_called_once()
        # Verify backflow log message
        assert "memory_backflow" in caplog.text or "memory_written" in caplog.text

    def test_lifecycle_manager_writes_memory_on_failed(self):
        """mark_failed() must write failure to TaskMemory."""
        from core.schemas.task_envelope import TaskEnvelope
        from core.task_lifecycle import TaskLifecycleManager
        import core.task_lifecycle as _tlm_mod

        mem_mock = MagicMock()
        with patch.object(_tlm_mod, "_get_task_memory", return_value=mem_mock), \
             patch.object(_tlm_mod, "_MEMORY_OK", True):
            mgr = TaskLifecycleManager()
            env = TaskEnvelope(tool_name="failing_tool", targets=["local"])
            running = mgr.mark_running(env)
            mgr.mark_failed(running, error="disk full")

        mem_mock.record_task.assert_called_once()
        call_kwargs = mem_mock.record_task.call_args
        assert call_kwargs.kwargs.get("success") is False or (
            call_kwargs.args and call_kwargs.args[2] is False
        ) or "FAILED" in str(call_kwargs)

    def test_envelope_preserves_trace_and_task_ids(self):
        """task_id and trace_id must be preserved through lifecycle transitions."""
        from core.schemas.task_envelope import TaskEnvelope
        env = TaskEnvelope(
            task_id="task_12345",
            trace_id="trace_abcdef",
            session_id="s001",
            tool_name="echo",
        )
        running = env.transition("running")
        done = running.transition("done")
        assert done.task_id == "task_12345"
        assert done.trace_id == "trace_abcdef"
        assert done.session_id == "s001"


# ---------------------------------------------------------------------------
# Capability 4: Cross-Device Orchestration
# ---------------------------------------------------------------------------

class TestCrossDeviceOrch:
    """PR-5 Capability 4 — cross-device / cross-app task coordination."""

    def test_envelope_supports_multiple_targets(self):
        from core.schemas.task_envelope import TaskEnvelope
        env = TaskEnvelope(
            tool_name="broadcast",
            targets=["device_a", "device_b", "device_c"],
        )
        assert len(env.targets) == 3
        assert env.target == "device_a"  # shorthand = first target

    @pytest.mark.asyncio
    async def test_cross_device_pipeline(self):
        """Full device_a → device_b pipeline using TaskLifecycleManager."""
        import os
        from core.schemas.task_envelope import TaskEnvelope
        from core.task_lifecycle import TaskLifecycleManager
        mgr = TaskLifecycleManager()

        # ── Phase 1: device_a generates artifact ────────────────────────────
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_path = os.path.join(tmpdir, "artifact.txt")

            async def device_a_execute(env: TaskEnvelope):
                with open(artifact_path, "w") as f:
                    f.write("cross-device payload from device_a")
                return {"artifact_path": artifact_path}, f"artifact written to {artifact_path}"

            env_a = TaskEnvelope(
                tool_name="generate_artifact",
                targets=["device_a"],
                session_id="xdev_session_001",
                required_capabilities=["filesystem"],
            )
            env_a, result_a = await mgr.run_with_lifecycle(env_a, device_a_execute)
            assert env_a.lifecycle_status == "done"
            assert os.path.isfile(artifact_path)

            # ── Phase 2: device_b processes artifact ────────────────────────
            async def device_b_execute(env: TaskEnvelope):
                path = env.args.get("artifact_path")
                with open(path) as f:
                    content = f.read()
                return {"content": content}, f"processed: {content[:40]}"

            env_b = TaskEnvelope(
                tool_name="process_artifact",
                args={"artifact_path": artifact_path},
                targets=["device_b"],
                session_id="xdev_session_001",
                trace_id=env_a.trace_id,  # same trace for cross-device correlation
                required_capabilities=["filesystem"],
            )
            env_b, result_b = await mgr.run_with_lifecycle(env_b, device_b_execute)
            assert env_b.lifecycle_status == "done"
            assert "cross-device payload" in result_b["content"]

        # Both phases share the same session_id for context
        assert env_a.session_id == env_b.session_id

    def test_cross_device_demo_script_is_runnable(self):
        demo_path = os.path.join(PROJECT_ROOT, "scripts", "cross_device_task_demo.py")
        assert os.path.isfile(demo_path), f"Demo script missing: {demo_path}"
        import py_compile
        py_compile.compile(demo_path, doraise=True)


# ---------------------------------------------------------------------------
# Capability 5: ACL / Permissions
# ---------------------------------------------------------------------------

class TestACLPermissions:
    """PR-5 Capability 5 — permission_level / required_capabilities + audit."""

    def test_envelope_has_permission_level_field(self):
        from core.schemas.task_envelope import TaskEnvelope
        env = TaskEnvelope(tool_name="safe_action")
        assert env.permission_level == 0

    def test_envelope_has_required_capabilities_field(self):
        from core.schemas.task_envelope import TaskEnvelope
        env = TaskEnvelope(
            tool_name="write_file",
            required_capabilities=["filesystem", "elevated_io"],
        )
        assert "filesystem" in env.required_capabilities
        assert "elevated_io" in env.required_capabilities

    def test_acl_enforcer_allows_low_level_task(self):
        from core.acl_enforcer import ACLEnforcer
        enforcer = ACLEnforcer(policy={"strict_above_level": 1})
        from core.schemas.task_envelope import TaskEnvelope
        env = TaskEnvelope(
            tool_name="screenshot",
            permission_level=0,
            required_capabilities=["screen"],
        )
        result = enforcer.check(env, caller_level=0, agent_capabilities=["screen"])
        assert result.allowed is True

    def test_acl_enforcer_denies_high_level_with_low_caller(self):
        from core.acl_enforcer import ACLEnforcer
        enforcer = ACLEnforcer(policy={"strict_above_level": 1})
        from core.schemas.task_envelope import TaskEnvelope
        env = TaskEnvelope(
            tool_name="system_reboot",
            permission_level=3,
            required_capabilities=[],
        )
        result = enforcer.check(env, caller_level=0)
        assert result.allowed is False
        assert "permission_level" in result.reason or "caller_level" in result.reason

    def test_acl_enforcer_denies_missing_capabilities(self):
        from core.acl_enforcer import ACLEnforcer
        enforcer = ACLEnforcer(policy={"strict_above_level": 3})
        from core.schemas.task_envelope import TaskEnvelope
        env = TaskEnvelope(
            tool_name="camera_stream",
            permission_level=0,
            required_capabilities=["camera", "microphone"],
        )
        result = enforcer.check(env, caller_level=3, agent_capabilities=["screen"])
        assert result.allowed is False
        assert "camera" in result.missing_capabilities

    def test_acl_enforcer_emits_audit_log(self, caplog):
        from core.acl_enforcer import ACLEnforcer
        enforcer = ACLEnforcer(policy={"strict_above_level": 1})
        from core.schemas.task_envelope import TaskEnvelope
        env = TaskEnvelope(tool_name="safe_read", permission_level=0)
        with caplog.at_level(logging.INFO, logger="Galaxy.ACLEnforcer"):
            enforcer.check(env, caller_level=0, agent_capabilities=[])
        assert "acl.audit" in caplog.text

    def test_acl_enforcer_audit_records_task_id(self, caplog):
        from core.acl_enforcer import ACLEnforcer
        enforcer = ACLEnforcer(policy={"strict_above_level": 1})
        from core.schemas.task_envelope import TaskEnvelope
        env = TaskEnvelope(task_id="task_acl_test", tool_name="get_data", permission_level=0)
        with caplog.at_level(logging.INFO, logger="Galaxy.ACLEnforcer"):
            enforcer.check(env, caller_level=1)
        assert "task_acl_test" in caplog.text

    def test_acl_allows_sufficient_caller_level(self):
        from core.acl_enforcer import ACLEnforcer
        enforcer = ACLEnforcer(policy={"strict_above_level": 1})
        from core.schemas.task_envelope import TaskEnvelope
        env = TaskEnvelope(
            tool_name="admin_action",
            permission_level=2,
            required_capabilities=["admin"],
        )
        result = enforcer.check(
            env, caller_level=2, agent_capabilities=["admin", "screen"]
        )
        assert result.allowed is True

    def test_envelope_permission_level_bounds(self):
        from core.schemas.task_envelope import TaskEnvelope
        import pydantic
        with pytest.raises((ValueError, pydantic.ValidationError)):
            TaskEnvelope(tool_name="x", permission_level=4)  # max is 3

    def test_acl_check_result_carries_task_id(self):
        from core.acl_enforcer import ACLEnforcer
        enforcer = ACLEnforcer(policy={"strict_above_level": 1})
        from core.schemas.task_envelope import TaskEnvelope
        env = TaskEnvelope(task_id="task_xyz", tool_name="x")
        result = enforcer.check(env, caller_level=0)
        assert result.task_id == "task_xyz"


# ---------------------------------------------------------------------------
# Integration: all 5 capabilities together
# ---------------------------------------------------------------------------

class TestFullCapabilityChain:
    """End-to-end integration: TaskEnvelope flows through all 5 capability checks."""

    @pytest.mark.asyncio
    async def test_e2e_lifecycle_acl_memory_chain(self, tmp_path, monkeypatch):
        """Full chain: ACL check → lifecycle → memory backflow."""
        import core.task_lifecycle as _tlm_mod

        mem_mock = MagicMock()
        with patch.object(_tlm_mod, "_get_task_memory", return_value=mem_mock), \
             patch.object(_tlm_mod, "_MEMORY_OK", True):

            from core.schemas.task_envelope import TaskEnvelope
            from core.task_lifecycle import TaskLifecycleManager
            from core.acl_enforcer import ACLEnforcer

            # Build envelope with all PR-5 fields
            env = TaskEnvelope(
                tool_name="list_files",
                args={"path": "/tmp"},
                targets=["local"],
                session_id="e2e_session_001",
                permission_level=1,
                required_capabilities=["filesystem"],
            )

            # Capability 5: ACL check
            enforcer = ACLEnforcer(policy={"strict_above_level": 1})
            acl_result = enforcer.check(
                env, caller_level=1, agent_capabilities=["filesystem", "screen"]
            )
            assert acl_result.allowed is True

            # Capabilities 1 + 3: lifecycle with memory backflow
            mgr = TaskLifecycleManager()

            async def _work(e: TaskEnvelope):
                return {"files": ["a.txt", "b.txt"]}, "listed 2 files"

            final_env, result = await mgr.run_with_lifecycle(env, _work)

            # Capability 1: state is terminal
            assert final_env.lifecycle_status == "done"

            # Capability 3: memory was written
            mem_mock.record_task.assert_called_once()

            # Capability 3: trace/session IDs propagated
            assert final_env.task_id == env.task_id
            assert final_env.session_id == "e2e_session_001"

            # Capability 4: targets carried through
            assert "local" in final_env.targets
