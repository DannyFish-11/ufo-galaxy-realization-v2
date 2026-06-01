"""tests/test_prd_source_dispatch_orchestrator_production_wiring.py
====================================================================
Tests for PR-D: Source Dispatch Orchestrator Production Wiring.

Coverage:
  1.  _delegate_multi_device_orchestration with mesh session (2+ active
      participants) calls orchestrate_source_runtime_dispatch and returns a
      staged_mesh result when the orchestrator succeeds.
  2.  _delegate_multi_device_orchestration falls back to _dispatch_parallel_goal
      when no mesh session is available.
  3.  _delegate_multi_device_orchestration falls back to _dispatch_parallel_goal
      when orchestrate_source_runtime_dispatch returns a non-staged_mesh result.
  4.  _delegate_multi_device_orchestration falls back to _dispatch_parallel_goal
      when orchestrate_source_runtime_dispatch raises an exception.
  5.  _delegate_multi_device_orchestration result carries
      delegation_point="multi_device_orchestration" in all code paths.
  6.  orchestrate_source_runtime_dispatch is accessible as a real production
      caller via the multi-device orchestration delegation boundary.
  7.  SourceDispatchPlan is built during staged_mesh production dispatch.
  8.  staged_mesh mode is reachable via _delegate_multi_device_orchestration when
      a qualifying mesh session is present.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mesh_session_dict(participant_count: int = 3) -> Dict[str, Any]:
    """Return a minimal mesh session dict with *participant_count* active members."""
    participants = [
        {
            "device_id": f"dev_{i}",
            "status": "active",
            "role": "participant",
        }
        for i in range(participant_count)
    ]
    return {
        "session_id": str(uuid.uuid4()),
        "mesh_id": "test_mesh",
        "participants": participants,
        "status": "active",
    }


def _make_openclawd_instance():
    """Return a minimal OpenClawd instance suitable for unit testing."""
    from core.openclawd import OpenClawd

    oc = object.__new__(OpenClawd)
    # Minimal attribute stubs so __init__ side-effects are avoided
    oc._cancelled_tasks = set()
    oc._cancelled_groups = set()
    oc.agent_kernel = None
    return oc


# ---------------------------------------------------------------------------
# 1. staged_mesh path: orchestrator succeeds
# ---------------------------------------------------------------------------


class TestStagedMeshProductionPath:
    """When a mesh session with 2+ active participants is present,
    _delegate_multi_device_orchestration must call
    orchestrate_source_runtime_dispatch and return the staged_mesh result."""

    def test_staged_mesh_result_returned_on_success(self):
        from contracts.source_dispatch import SourceDispatchMode

        mesh_dict = _make_mesh_session_dict(participant_count=3)

        # Build a fake SourceDispatchResult-like object
        fake_result = MagicMock()
        fake_result.mode = SourceDispatchMode.staged_mesh
        fake_result.success = True
        fake_result.dispatch_id = "disp_001"
        fake_result.decision_reason = "staged_mesh:coordinated"
        fake_result.result = {
            "action_taken": "staged_mesh_coordinated",
            "coordinator_status": "coordinated",
        }

        oc = _make_openclawd_instance()

        async def run():
            with patch(
                "core.runtime.source_dispatch_orchestrator._try_mesh_session",
                return_value=mesh_dict,
            ), patch(
                "core.runtime.source_dispatch_orchestrator.orchestrate_source_runtime_dispatch",
                return_value=fake_result,
            ):
                return await oc._delegate_multi_device_orchestration(
                    message="run mesh task",
                    trace_id="trace_prd_01",
                    session_id="sess_001",
                )

        result = asyncio.get_running_loop().run_until_complete(run())

        assert result["success"] is True
        assert result["metadata"]["delegation_point"] == "multi_device_orchestration"
        assert result["metadata"]["dispatch_mode"] == "staged_mesh"

    def test_staged_mesh_response_carries_action_taken(self):
        from contracts.source_dispatch import SourceDispatchMode

        mesh_dict = _make_mesh_session_dict(participant_count=2)

        fake_result = MagicMock()
        fake_result.mode = SourceDispatchMode.staged_mesh
        fake_result.success = True
        fake_result.dispatch_id = "disp_002"
        fake_result.decision_reason = "staged_mesh:coordinated"
        fake_result.result = {
            "action_taken": "staged_mesh_coordinated",
            "coordinator_status": "active",
        }

        oc = _make_openclawd_instance()

        async def run():
            with patch(
                "core.runtime.source_dispatch_orchestrator._try_mesh_session",
                return_value=mesh_dict,
            ), patch(
                "core.runtime.source_dispatch_orchestrator.orchestrate_source_runtime_dispatch",
                return_value=fake_result,
            ):
                return await oc._delegate_multi_device_orchestration(
                    message="staged mesh",
                    trace_id="trace_prd_02",
                )

        result = asyncio.get_running_loop().run_until_complete(run())
        assert result["response"] == "staged_mesh_coordinated"


# ---------------------------------------------------------------------------
# 2. Fallback: no mesh session
# ---------------------------------------------------------------------------


class TestFallbackNoMeshSession:
    """When no mesh session is available, _delegate_multi_device_orchestration
    must fall back to _dispatch_parallel_goal without error."""

    def test_falls_back_to_parallel_goal_when_no_mesh(self):
        oc = _make_openclawd_instance()

        parallel_called = []

        async def fake_parallel_goal(**kwargs):
            parallel_called.append(True)
            return {"success": True, "response": "parallel done", "metadata": {}}

        oc._dispatch_parallel_goal = fake_parallel_goal

        async def run():
            with patch(
                "core.runtime.source_dispatch_orchestrator._try_mesh_session",
                return_value=None,
            ):
                return await oc._delegate_multi_device_orchestration(
                    message="no mesh task",
                    trace_id="trace_prd_03",
                )

        result = asyncio.get_running_loop().run_until_complete(run())

        assert parallel_called, "_dispatch_parallel_goal was not called as fallback"
        assert result["metadata"]["delegation_point"] == "multi_device_orchestration"

    def test_falls_back_when_mesh_has_only_one_active_participant(self):
        """Only 1 active participant — orchestrator won't select staged_mesh."""
        oc = _make_openclawd_instance()

        parallel_called = []

        async def fake_parallel_goal(**kwargs):
            parallel_called.append(True)
            return {"success": False, "response": "no devices", "metadata": {}}

        oc._dispatch_parallel_goal = fake_parallel_goal

        single_participant_mesh = {
            "session_id": "s1",
            "participants": [{"device_id": "dev_0", "status": "active"}],
        }

        async def run():
            with patch(
                "core.runtime.source_dispatch_orchestrator._try_mesh_session",
                return_value=single_participant_mesh,
            ):
                return await oc._delegate_multi_device_orchestration(
                    message="single participant",
                    trace_id="trace_prd_04",
                )

        result = asyncio.get_running_loop().run_until_complete(run())
        assert parallel_called


# ---------------------------------------------------------------------------
# 3. Fallback: orchestrator returns non-staged_mesh result
# ---------------------------------------------------------------------------


class TestFallbackNonStagedMeshResult:
    """When the orchestrator returns a non-staged_mesh mode (e.g. local),
    _delegate_multi_device_orchestration must fall back to
    _dispatch_parallel_goal."""

    def test_fallback_when_orchestrator_returns_local(self):
        from contracts.source_dispatch import SourceDispatchMode

        mesh_dict = _make_mesh_session_dict(participant_count=3)

        local_result = MagicMock()
        local_result.mode = SourceDispatchMode.local
        local_result.success = True
        local_result.dispatch_id = "disp_003"
        local_result.decision_reason = "default_local"
        local_result.result = {"action_taken": "local_execution"}

        oc = _make_openclawd_instance()
        parallel_called = []

        async def fake_parallel_goal(**kwargs):
            parallel_called.append(True)
            return {"success": True, "response": "parallel ok", "metadata": {}}

        oc._dispatch_parallel_goal = fake_parallel_goal

        async def run():
            with patch(
                "core.runtime.source_dispatch_orchestrator._try_mesh_session",
                return_value=mesh_dict,
            ), patch(
                "core.runtime.source_dispatch_orchestrator.orchestrate_source_runtime_dispatch",
                return_value=local_result,
            ):
                return await oc._delegate_multi_device_orchestration(
                    message="local mode",
                    trace_id="trace_prd_05",
                )

        result = asyncio.get_running_loop().run_until_complete(run())
        assert parallel_called, "Expected fallback to _dispatch_parallel_goal"
        assert result["metadata"]["delegation_point"] == "multi_device_orchestration"

    def test_fallback_when_orchestrator_reports_not_success(self):
        from contracts.source_dispatch import SourceDispatchMode

        mesh_dict = _make_mesh_session_dict(participant_count=3)

        failed_result = MagicMock()
        failed_result.mode = SourceDispatchMode.staged_mesh
        failed_result.success = False
        failed_result.dispatch_id = "disp_004"
        failed_result.decision_reason = "staged_mesh:coordinator_error"
        failed_result.result = {}

        oc = _make_openclawd_instance()
        parallel_called = []

        async def fake_parallel_goal(**kwargs):
            parallel_called.append(True)
            return {"success": False, "response": "no devices", "metadata": {}}

        oc._dispatch_parallel_goal = fake_parallel_goal

        async def run():
            with patch(
                "core.runtime.source_dispatch_orchestrator._try_mesh_session",
                return_value=mesh_dict,
            ), patch(
                "core.runtime.source_dispatch_orchestrator.orchestrate_source_runtime_dispatch",
                return_value=failed_result,
            ):
                return await oc._delegate_multi_device_orchestration(
                    message="failed mesh",
                    trace_id="trace_prd_06",
                )

        result = asyncio.get_running_loop().run_until_complete(run())
        assert parallel_called


# ---------------------------------------------------------------------------
# 4. Fallback: orchestrator raises
# ---------------------------------------------------------------------------


class TestFallbackOnOrchestratorException:
    """If orchestrate_source_runtime_dispatch raises, the exception must be
    swallowed and _dispatch_parallel_goal must still be called."""

    def test_exception_in_orchestrator_is_non_fatal(self):
        mesh_dict = _make_mesh_session_dict(participant_count=3)

        oc = _make_openclawd_instance()
        parallel_called = []

        async def fake_parallel_goal(**kwargs):
            parallel_called.append(True)
            return {"success": True, "response": "recovered", "metadata": {}}

        oc._dispatch_parallel_goal = fake_parallel_goal

        async def run():
            with patch(
                "core.runtime.source_dispatch_orchestrator._try_mesh_session",
                return_value=mesh_dict,
            ), patch(
                "core.runtime.source_dispatch_orchestrator.orchestrate_source_runtime_dispatch",
                side_effect=RuntimeError("unexpected orchestrator failure"),
            ):
                return await oc._delegate_multi_device_orchestration(
                    message="error case",
                    trace_id="trace_prd_07",
                )

        result = asyncio.get_running_loop().run_until_complete(run())
        assert parallel_called, "Fallback was not triggered after orchestrator exception"
        assert result["metadata"]["delegation_point"] == "multi_device_orchestration"


# ---------------------------------------------------------------------------
# 5. delegation_point is always set
# ---------------------------------------------------------------------------


class TestDelegationPointAlwaysSet:
    """delegation_point="multi_device_orchestration" must appear in metadata
    for every possible code path."""

    def _run_with_parallel_stub(self, mesh_dict, orch_result=None):
        from contracts.source_dispatch import SourceDispatchMode

        oc = _make_openclawd_instance()

        async def fake_parallel_goal(**kwargs):
            return {"success": True, "response": "done", "metadata": {}}

        oc._dispatch_parallel_goal = fake_parallel_goal

        async def run():
            patches = [
                patch(
                    "core.runtime.source_dispatch_orchestrator._try_mesh_session",
                    return_value=mesh_dict,
                )
            ]
            if orch_result is not None:
                patches.append(
                    patch(
                        "core.runtime.source_dispatch_orchestrator.orchestrate_source_runtime_dispatch",
                        return_value=orch_result,
                    )
                )
            with patches[0]:
                if len(patches) > 1:
                    with patches[1]:
                        return await oc._delegate_multi_device_orchestration(
                            message="test", trace_id="trace_dp"
                        )
                return await oc._delegate_multi_device_orchestration(
                    message="test", trace_id="trace_dp"
                )

        return asyncio.get_running_loop().run_until_complete(run())

    def test_delegation_point_set_no_mesh(self):
        result = self._run_with_parallel_stub(mesh_dict=None)
        assert result["metadata"]["delegation_point"] == "multi_device_orchestration"

    def test_delegation_point_set_fallback_path(self):
        from contracts.source_dispatch import SourceDispatchMode

        local_result = MagicMock()
        local_result.mode = SourceDispatchMode.local
        local_result.success = True
        local_result.dispatch_id = "d5"
        local_result.decision_reason = "default_local"
        local_result.result = {}

        result = self._run_with_parallel_stub(
            mesh_dict=_make_mesh_session_dict(participant_count=3),
            orch_result=local_result,
        )
        assert result["metadata"]["delegation_point"] == "multi_device_orchestration"

    def test_delegation_point_set_staged_mesh_path(self):
        from contracts.source_dispatch import SourceDispatchMode

        fake_result = MagicMock()
        fake_result.mode = SourceDispatchMode.staged_mesh
        fake_result.success = True
        fake_result.dispatch_id = "d6"
        fake_result.decision_reason = "staged_mesh:coordinated"
        fake_result.result = {"action_taken": "staged_mesh_coordinated"}

        oc = _make_openclawd_instance()

        async def run():
            with patch(
                "core.runtime.source_dispatch_orchestrator._try_mesh_session",
                return_value=_make_mesh_session_dict(participant_count=3),
            ), patch(
                "core.runtime.source_dispatch_orchestrator.orchestrate_source_runtime_dispatch",
                return_value=fake_result,
            ):
                return await oc._delegate_multi_device_orchestration(
                    message="staged mesh", trace_id="trace_dp2"
                )

        result = asyncio.get_running_loop().run_until_complete(run())
        assert result["metadata"]["delegation_point"] == "multi_device_orchestration"


# ---------------------------------------------------------------------------
# 6. Production caller existence check
# ---------------------------------------------------------------------------


class TestProductionCallerExists:
    """orchestrate_source_runtime_dispatch must be invoked from within
    _delegate_multi_device_orchestration source code."""

    def test_orchestrate_called_in_method_source(self):
        import inspect
        from core.openclawd import OpenClawd

        source = inspect.getsource(OpenClawd._delegate_multi_device_orchestration)
        assert "orchestrate_source_runtime_dispatch" in source, (
            "_delegate_multi_device_orchestration does not reference "
            "orchestrate_source_runtime_dispatch — production wiring missing"
        )

    def test_source_dispatch_plan_built_via_orchestrate(self):
        """orchestrate_source_runtime_dispatch calls build_source_dispatch_plan
        internally, so SourceDispatchPlan is part of the production dispatch flow
        whenever the orchestrator is invoked."""
        import inspect
        from core.runtime.source_dispatch_orchestrator import (
            orchestrate_source_runtime_dispatch,
        )

        source = inspect.getsource(orchestrate_source_runtime_dispatch)
        assert "build_source_dispatch_plan" in source, (
            "orchestrate_source_runtime_dispatch does not call "
            "build_source_dispatch_plan — SourceDispatchPlan not part of flow"
        )


# ---------------------------------------------------------------------------
# 7. SourceDispatchPlan usage in real dispatch flow
# ---------------------------------------------------------------------------


class TestSourceDispatchPlanInProductionFlow:
    """When the production path is triggered, SourceDispatchPlan must be built."""

    def test_plan_built_during_staged_mesh_dispatch(self):
        """build_source_dispatch_plan is called during orchestrate_source_runtime_dispatch."""
        from contracts.source_dispatch import SourceDispatchMode

        mesh_dict = _make_mesh_session_dict(participant_count=3)

        plan_built = []

        real_orchestrate = None
        try:
            from core.runtime.source_dispatch_orchestrator import (
                orchestrate_source_runtime_dispatch as _real,
            )
            real_orchestrate = _real
        except ImportError:
            pytest.skip("orchestrate_source_runtime_dispatch not available")

        from core.runtime import source_dispatch_orchestrator as _mod

        original_build = getattr(_mod, "build_source_dispatch_plan", None)
        if original_build is None:
            pytest.skip("build_source_dispatch_plan not accessible from module")

        def recording_build(**kwargs):
            plan_built.append(True)
            return original_build(**kwargs)

        with patch.object(_mod, "build_source_dispatch_plan", side_effect=recording_build):
            result = real_orchestrate(
                trace_id="trace_plan_check",
                mesh_session=mesh_dict,
                policy_alignment=None,
                governance_snapshot=None,
                mesh_memberships=None,
            )

        assert plan_built, (
            "build_source_dispatch_plan was not called during "
            "orchestrate_source_runtime_dispatch — SourceDispatchPlan not in flow"
        )
        assert result is not None


# ---------------------------------------------------------------------------
# 8. staged_mesh reachable via _delegate_multi_device_orchestration
# ---------------------------------------------------------------------------


class TestStagedMeshReachable:
    """staged_mesh mode must be reachable via the production multi-device
    delegation path when a qualifying mesh session is present."""

    def test_staged_mesh_reachable_end_to_end(self):
        """End-to-end: _delegate_multi_device_orchestration with a valid mesh
        session (3 active participants) results in a staged_mesh dispatch."""
        from contracts.source_dispatch import SourceDispatchMode

        mesh_dict = _make_mesh_session_dict(participant_count=3)

        fake_result = MagicMock()
        fake_result.mode = SourceDispatchMode.staged_mesh
        fake_result.success = True
        fake_result.dispatch_id = "disp_e2e"
        fake_result.decision_reason = "staged_mesh:coordinated"
        fake_result.result = {
            "action_taken": "staged_mesh_coordinated",
            "coordinator_status": "coordinated",
        }

        oc = _make_openclawd_instance()

        async def run():
            with patch(
                "core.runtime.source_dispatch_orchestrator._try_mesh_session",
                return_value=mesh_dict,
            ), patch(
                "core.runtime.source_dispatch_orchestrator.orchestrate_source_runtime_dispatch",
                return_value=fake_result,
            ):
                return await oc._delegate_multi_device_orchestration(
                    message="end-to-end staged mesh",
                    trace_id="trace_e2e",
                    session_id="sess_e2e",
                )

        result = asyncio.get_running_loop().run_until_complete(run())

        assert result["success"] is True
        assert result["metadata"]["dispatch_mode"] == "staged_mesh"
        assert result["metadata"]["delegation_point"] == "multi_device_orchestration"

    def test_staged_mesh_not_triggered_below_threshold(self):
        """With only 1 active participant, staged_mesh must NOT be triggered."""
        oc = _make_openclawd_instance()
        staged_mesh_triggered = []

        async def fake_parallel_goal(**kwargs):
            return {"success": True, "response": "parallel", "metadata": {}}

        oc._dispatch_parallel_goal = fake_parallel_goal

        thin_mesh = {
            "session_id": "thin",
            "participants": [{"device_id": "dev_0", "status": "active"}],
        }

        async def run():
            with patch(
                "core.runtime.source_dispatch_orchestrator._try_mesh_session",
                return_value=thin_mesh,
            ), patch(
                "core.runtime.source_dispatch_orchestrator.orchestrate_source_runtime_dispatch",
                side_effect=lambda **kw: staged_mesh_triggered.append(True) or MagicMock(),
            ):
                return await oc._delegate_multi_device_orchestration(
                    message="thin mesh",
                    trace_id="trace_thin",
                )

        asyncio.get_running_loop().run_until_complete(run())
        assert not staged_mesh_triggered, (
            "orchestrate_source_runtime_dispatch was called with only 1 active "
            "participant — staged_mesh threshold not enforced"
        )
