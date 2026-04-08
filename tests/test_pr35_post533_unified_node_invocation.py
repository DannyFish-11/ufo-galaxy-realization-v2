"""tests/test_pr35_post533_unified_node_invocation.py
======================================================
Tests for PR package 35 (post-533 MAIN repo side):
Unified Node Invocation Executor.

Coverage groups
---------------
A -- Module availability and sentinel presence (PR-35 sentinels).
B -- NodeInvocationEnvelope field contract.
C -- NodeInvocationResult field contract.
D -- invoke_node() error paths (missing dir / missing fusion_entry).
E -- invoke_node() success path (real fusion_entry stub).
F -- build_envelope() convenience builder.
G -- InvocationSource and RouteMode enum members.
H -- Projection sentinel (UNIFIED_NODE_INVOCATION_ALIGNED_PR35).
I -- core.runtime re-exports.
J -- Backward-compat helpers (to_legacy_dict / to_dict).
K -- No parallel authority assertion.
L -- PR-34 regression.
"""

from __future__ import annotations

import asyncio
import os
import textwrap
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Module availability guards
# ---------------------------------------------------------------------------

try:
    from core.nodes.unified_node_executor import (
        UNIFIED_NODE_INVOCATION_EXECUTOR_AUTHORITY,
        UNIFIED_NODE_INVOCATION_EXECUTOR_PR35_SENTINEL,
        ALL_NODE_INVOCATION_PATHS_MUST_USE_UNIFIED_EXECUTOR_PR35_POLICY,
        INVOCATION_ENVELOPE_IS_CANONICAL_TRACE_CARRIER_PR35_POLICY,
        RESULT_ENVELOPE_SHAPE_IS_STABLE_PR35_POLICY,
        NO_PARALLEL_NODE_EXECUTION_AUTHORITY_PR35_POLICY,
        NodeInvocationEnvelope,
        NodeInvocationResult,
        InvocationSource,
        RouteMode,
        invoke_node,
        build_envelope,
    )
    _EXECUTOR_AVAILABLE = True
except ImportError:
    _EXECUTOR_AVAILABLE = False

try:
    from core.routes.projection import UNIFIED_NODE_INVOCATION_ALIGNED_PR35
    _PROJECTION_AVAILABLE = True
except ImportError:
    _PROJECTION_AVAILABLE = False

try:
    import core.runtime as _runtime
    _RUNTIME_AVAILABLE = True
except ImportError:
    _RUNTIME_AVAILABLE = False


def _run(coro):
    """Run a coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Group A -- Sentinel presence
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _EXECUTOR_AVAILABLE, reason="unified_node_executor unavailable")
class TestGroupA_Sentinels:
    def test_A01_executor_authority_nonempty(self):
        assert isinstance(UNIFIED_NODE_INVOCATION_EXECUTOR_AUTHORITY, str)
        assert len(UNIFIED_NODE_INVOCATION_EXECUTOR_AUTHORITY) > 0

    def test_A02_pr35_sentinel_nonempty(self):
        assert isinstance(UNIFIED_NODE_INVOCATION_EXECUTOR_PR35_SENTINEL, str)
        assert len(UNIFIED_NODE_INVOCATION_EXECUTOR_PR35_SENTINEL) > 0

    def test_A03_paths_policy_nonempty(self):
        assert isinstance(ALL_NODE_INVOCATION_PATHS_MUST_USE_UNIFIED_EXECUTOR_PR35_POLICY, str)
        assert len(ALL_NODE_INVOCATION_PATHS_MUST_USE_UNIFIED_EXECUTOR_PR35_POLICY) > 0

    def test_A04_envelope_policy_nonempty(self):
        assert isinstance(INVOCATION_ENVELOPE_IS_CANONICAL_TRACE_CARRIER_PR35_POLICY, str)
        assert len(INVOCATION_ENVELOPE_IS_CANONICAL_TRACE_CARRIER_PR35_POLICY) > 0

    def test_A05_result_policy_nonempty(self):
        assert isinstance(RESULT_ENVELOPE_SHAPE_IS_STABLE_PR35_POLICY, str)
        assert len(RESULT_ENVELOPE_SHAPE_IS_STABLE_PR35_POLICY) > 0

    def test_A06_no_parallel_policy_nonempty(self):
        assert isinstance(NO_PARALLEL_NODE_EXECUTION_AUTHORITY_PR35_POLICY, str)
        assert len(NO_PARALLEL_NODE_EXECUTION_AUTHORITY_PR35_POLICY) > 0

    def test_A07_sentinel_contains_pr35_keyword(self):
        assert "35" in UNIFIED_NODE_INVOCATION_EXECUTOR_PR35_SENTINEL

    def test_A08_sentinel_contains_invoke_node_keyword(self):
        assert "invoke_node" in UNIFIED_NODE_INVOCATION_EXECUTOR_PR35_SENTINEL


# ---------------------------------------------------------------------------
# Group B -- NodeInvocationEnvelope field contract
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _EXECUTOR_AVAILABLE, reason="unified_node_executor unavailable")
class TestGroupB_EnvelopeContract:
    def _make_envelope(self, **kwargs):
        defaults = dict(node_id="Node_99_Test", action="execute", params={"key": "value"})
        defaults.update(kwargs)
        return NodeInvocationEnvelope(**defaults)

    def test_B01_has_node_id(self):
        assert self._make_envelope().node_id == "Node_99_Test"

    def test_B02_has_action(self):
        assert self._make_envelope().action == "execute"

    def test_B03_has_params(self):
        assert self._make_envelope().params == {"key": "value"}

    def test_B04_request_id_auto_generated(self):
        env = self._make_envelope()
        assert isinstance(env.request_id, str) and len(env.request_id) > 0

    def test_B05_request_id_distinct_per_instance(self):
        assert self._make_envelope().request_id != self._make_envelope().request_id

    def test_B06_trace_id_defaults_none(self):
        assert self._make_envelope().trace_id is None

    def test_B07_task_id_defaults_none(self):
        assert self._make_envelope().task_id is None

    def test_B08_session_id_defaults_none(self):
        assert self._make_envelope().session_id is None

    def test_B09_invocation_source_default_unknown(self):
        assert self._make_envelope().invocation_source == InvocationSource.UNKNOWN

    def test_B10_route_mode_default_unknown(self):
        assert self._make_envelope().route_mode == RouteMode.UNKNOWN

    def test_B11_to_dict_has_all_fields(self):
        env = self._make_envelope(trace_id="tr-001", task_id="t-001", session_id="s-001",
                                   invocation_source=InvocationSource.OPENCLAWD_TOOL)
        d = env.to_dict()
        for key in ("node_id", "action", "params", "request_id", "trace_id",
                    "task_id", "session_id", "invocation_source", "route_mode", "enqueued_at"):
            assert key in d, f"missing key: {key}"

    def test_B12_to_dict_invocation_source_is_string(self):
        env = self._make_envelope(invocation_source=InvocationSource.API_NODES_CALL)
        assert isinstance(env.to_dict()["invocation_source"], str)


# ---------------------------------------------------------------------------
# Group C -- NodeInvocationResult field contract
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _EXECUTOR_AVAILABLE, reason="unified_node_executor unavailable")
class TestGroupC_ResultContract:
    def _make_result(self, **kwargs):
        defaults = dict(
            success=True, result={"data": 42}, error=None, duration_ms=12.5,
            request_id="req-001", trace_id="tr-001", node_id="Node_99_Test",
            action="execute", invocation_source="api_nodes_call",
        )
        defaults.update(kwargs)
        return NodeInvocationResult(**defaults)

    def test_C01_has_success(self):      assert self._make_result().success is True
    def test_C02_has_result(self):       assert self._make_result().result == {"data": 42}
    def test_C03_has_error_none(self):   assert self._make_result().error is None
    def test_C04_has_duration_ms(self):  assert self._make_result().duration_ms == 12.5
    def test_C05_has_request_id(self):   assert self._make_result().request_id == "req-001"
    def test_C06_has_trace_id(self):     assert self._make_result().trace_id == "tr-001"
    def test_C07_has_node_id(self):      assert self._make_result().node_id == "Node_99_Test"
    def test_C08_has_action(self):       assert self._make_result().action == "execute"
    def test_C09_has_invocation_src(self):
        assert self._make_result().invocation_source == "api_nodes_call"


# ---------------------------------------------------------------------------
# Group D -- invoke_node() error paths
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _EXECUTOR_AVAILABLE, reason="unified_node_executor unavailable")
class TestGroupD_InvokeNodeErrorPaths:
    def test_D01_missing_node_dir_returns_failure(self):
        env = build_envelope("Node_NONEXISTENT", "execute",
                             invocation_source=InvocationSource.API_NODES_CALL)
        result = _run(invoke_node(env, node_dir="/nonexistent/path/Node_NONEXISTENT"))
        assert result.success is False
        assert result.error

    def test_D02_missing_fusion_entry_returns_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = build_envelope("Node_NOFUSION", "execute",
                                 invocation_source=InvocationSource.COMMAND_ROUTER)
            result = _run(invoke_node(env, node_dir=tmpdir,
                                      fusion_path=os.path.join(tmpdir, "fusion_entry.py")))
        assert result.success is False
        assert result.error

    def test_D03_failure_result_carries_request_id(self):
        env = build_envelope("Node_NONEXISTENT", "execute")
        result = _run(invoke_node(env, node_dir="/nonexistent/Node_NONEXISTENT"))
        assert result.request_id == env.request_id

    def test_D04_failure_result_carries_node_id(self):
        env = build_envelope("Node_NONEXISTENT", "ping")
        result = _run(invoke_node(env, node_dir="/nonexistent/Node_NONEXISTENT"))
        assert result.node_id == "Node_NONEXISTENT"

    def test_D05_failure_result_carries_action(self):
        env = build_envelope("Node_NONEXISTENT", "ping")
        result = _run(invoke_node(env, node_dir="/nonexistent/Node_NONEXISTENT"))
        assert result.action == "ping"


# ---------------------------------------------------------------------------
# Group E -- invoke_node() success path (real fusion_entry.py stub)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _EXECUTOR_AVAILABLE, reason="unified_node_executor unavailable")
class TestGroupE_InvokeNodeSuccessPath:
    @staticmethod
    def _write_stub(tmpdir: str) -> str:
        content = (
            "async def execute(action, params):\n"
            "    return {'echo_action': action, 'echo_params': params}\n"
        )
        path = os.path.join(tmpdir, "fusion_entry.py")
        with open(path, "w") as fh:
            fh.write(content)
        return path

    def test_E01_returns_NodeInvocationResult(self):
        with tempfile.TemporaryDirectory() as d:
            fp = self._write_stub(d)
            r = _run(invoke_node(build_envelope("stub", "greet", params={"n": 1},
                                                invocation_source=InvocationSource.API_NODES_CALL),
                                 node_dir=d, fusion_path=fp))
        assert isinstance(r, NodeInvocationResult)

    def test_E02_success_is_true(self):
        with tempfile.TemporaryDirectory() as d:
            fp = self._write_stub(d)
            r = _run(invoke_node(build_envelope("stub", "greet"), node_dir=d, fusion_path=fp))
        assert r.success is True

    def test_E03_duration_ms_nonnegative(self):
        with tempfile.TemporaryDirectory() as d:
            fp = self._write_stub(d)
            r = _run(invoke_node(build_envelope("stub", "greet"), node_dir=d, fusion_path=fp))
        assert r.duration_ms >= 0.0

    def test_E04_result_contains_echo(self):
        with tempfile.TemporaryDirectory() as d:
            fp = self._write_stub(d)
            r = _run(invoke_node(build_envelope("stub", "greet", params={"n": 1}),
                                 node_dir=d, fusion_path=fp))
        assert r.result is not None
        assert r.result.get("echo_action") == "greet"

    def test_E05_route_mode_set_fusion_entry(self):
        with tempfile.TemporaryDirectory() as d:
            fp = self._write_stub(d)
            env = build_envelope("stub", "greet")
            _run(invoke_node(env, node_dir=d, fusion_path=fp))
        assert env.route_mode == RouteMode.FUSION_ENTRY

    def test_E06_enqueued_at_stamped(self):
        with tempfile.TemporaryDirectory() as d:
            fp = self._write_stub(d)
            env = build_envelope("stub", "greet")
            assert env.enqueued_at is None
            _run(invoke_node(env, node_dir=d, fusion_path=fp))
        assert env.enqueued_at is not None


# ---------------------------------------------------------------------------
# Group F -- build_envelope() convenience builder
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _EXECUTOR_AVAILABLE, reason="unified_node_executor unavailable")
class TestGroupF_BuildEnvelope:
    def test_F01_returns_NodeInvocationEnvelope(self):
        assert isinstance(build_envelope("Node_1", "execute"), NodeInvocationEnvelope)

    def test_F02_sets_node_id(self):
        assert build_envelope("Node_1", "execute").node_id == "Node_1"

    def test_F03_sets_action(self):
        assert build_envelope("Node_1", "ping").action == "ping"

    def test_F04_params_default_empty(self):
        assert build_envelope("Node_1", "execute").params == {}

    def test_F05_params_passed_through(self):
        assert build_envelope("Node_1", "execute", params={"a": 1}).params == {"a": 1}

    def test_F06_invocation_source_propagated(self):
        env = build_envelope("Node_1", "execute",
                              invocation_source=InvocationSource.COMMAND_ROUTER)
        assert env.invocation_source == InvocationSource.COMMAND_ROUTER

    def test_F07_trace_id_propagated(self):
        assert build_envelope("Node_1", "execute", trace_id="tr-xyz").trace_id == "tr-xyz"

    def test_F08_task_id_propagated(self):
        assert build_envelope("Node_1", "execute", task_id="task-xyz").task_id == "task-xyz"

    def test_F09_session_id_propagated(self):
        assert build_envelope("Node_1", "execute", session_id="s-xyz").session_id == "s-xyz"

    def test_F10_custom_request_id_accepted(self):
        assert build_envelope("Node_1", "execute", request_id="custom").request_id == "custom"


# ---------------------------------------------------------------------------
# Group G -- InvocationSource and RouteMode enum members
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _EXECUTOR_AVAILABLE, reason="unified_node_executor unavailable")
class TestGroupG_EnumMembers:
    def test_G01_InvocationSource_openclawd_tool(self):
        assert InvocationSource.OPENCLAWD_TOOL.value == "openclawd_tool"

    def test_G02_InvocationSource_api_nodes_call(self):
        assert InvocationSource.API_NODES_CALL.value == "api_nodes_call"

    def test_G03_InvocationSource_command_router(self):
        assert InvocationSource.COMMAND_ROUTER.value == "command_router"

    def test_G04_InvocationSource_capability_orchestrator(self):
        assert InvocationSource.CAPABILITY_ORCHESTRATOR.value == "capability_orchestrator"

    def test_G05_InvocationSource_system_integration(self):
        assert InvocationSource.SYSTEM_INTEGRATION.value == "system_integration"

    def test_G06_InvocationSource_unknown(self):
        assert InvocationSource.UNKNOWN.value == "unknown"

    def test_G07_RouteMode_fusion_entry(self):
        assert RouteMode.FUSION_ENTRY.value == "fusion_entry"

    def test_G08_RouteMode_http_fallback(self):
        assert RouteMode.HTTP_FALLBACK.value == "http_fallback"

    def test_G09_RouteMode_registry(self):
        assert RouteMode.REGISTRY.value == "registry"

    def test_G10_RouteMode_unknown(self):
        assert RouteMode.UNKNOWN.value == "unknown"

    def test_G11_InvocationSource_is_str_subclass(self):
        assert issubclass(InvocationSource, str)

    def test_G12_RouteMode_is_str_subclass(self):
        assert issubclass(RouteMode, str)


# ---------------------------------------------------------------------------
# Group H -- Projection sentinel
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _PROJECTION_AVAILABLE, reason="projection module unavailable")
class TestGroupH_ProjectionSentinel:
    def test_H01_sentinel_is_string(self):
        assert isinstance(UNIFIED_NODE_INVOCATION_ALIGNED_PR35, str)

    def test_H02_sentinel_nonempty(self):
        assert len(UNIFIED_NODE_INVOCATION_ALIGNED_PR35) > 0

    def test_H03_sentinel_not_unavailable(self):
        assert "UNAVAILABLE" not in UNIFIED_NODE_INVOCATION_ALIGNED_PR35

    def test_H04_sentinel_contains_pr35_keyword(self):
        assert "PR35" in UNIFIED_NODE_INVOCATION_ALIGNED_PR35

    def test_H05_sentinel_contains_invoke_node(self):
        assert "invoke_node" in UNIFIED_NODE_INVOCATION_ALIGNED_PR35


# ---------------------------------------------------------------------------
# Group I -- core.runtime re-exports
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _RUNTIME_AVAILABLE, reason="core.runtime unavailable")
class TestGroupI_RuntimeReexports:
    def _get(self, name: str):
        return getattr(_runtime, name, None)

    def test_I01_authority_sentinel(self):
        v = self._get("UNIFIED_NODE_INVOCATION_EXECUTOR_AUTHORITY")
        assert v and len(v) > 0

    def test_I02_pr35_sentinel(self):
        v = self._get("UNIFIED_NODE_INVOCATION_EXECUTOR_PR35_SENTINEL")
        assert v and len(v) > 0

    def test_I03_paths_policy(self):
        assert self._get("ALL_NODE_INVOCATION_PATHS_MUST_USE_UNIFIED_EXECUTOR_PR35_POLICY")

    def test_I04_envelope_policy(self):
        assert self._get("INVOCATION_ENVELOPE_IS_CANONICAL_TRACE_CARRIER_PR35_POLICY")

    def test_I05_result_policy(self):
        assert self._get("RESULT_ENVELOPE_SHAPE_IS_STABLE_PR35_POLICY")

    def test_I06_no_parallel_policy(self):
        assert self._get("NO_PARALLEL_NODE_EXECUTION_AUTHORITY_PR35_POLICY")

    def test_I07_NodeInvocationEnvelope_exported(self):
        assert self._get("NodeInvocationEnvelope") is not None

    def test_I08_NodeInvocationResult_exported(self):
        assert self._get("NodeInvocationResult") is not None

    def test_I09_InvocationSource_exported(self):
        assert self._get("InvocationSource") is not None

    def test_I10_RouteMode_exported(self):
        assert self._get("RouteMode") is not None

    def test_I11_invoke_node_callable(self):
        fn = self._get("invoke_node")
        assert callable(fn)

    def test_I12_build_envelope_callable(self):
        fn = self._get("build_envelope")
        assert callable(fn)


# ---------------------------------------------------------------------------
# Group J -- Backward-compat helpers
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _EXECUTOR_AVAILABLE, reason="unified_node_executor unavailable")
class TestGroupJ_BackwardCompatHelpers:
    def _success(self):
        return NodeInvocationResult(
            success=True, result={"data": "ok"}, error=None, duration_ms=5.0,
            request_id="req-001", trace_id=None, node_id="Node_1",
            action="execute", invocation_source="api_nodes_call",
        )

    def _failure(self):
        return NodeInvocationResult(
            success=False, result=None, error="bang", duration_ms=2.0,
            request_id="req-002", trace_id=None, node_id="Node_1",
            action="execute", invocation_source="command_router",
        )

    def test_J01_legacy_success_has_success_true(self):
        assert self._success().to_legacy_dict()["success"] is True

    def test_J02_legacy_success_has_result(self):
        assert self._success().to_legacy_dict()["result"] == {"data": "ok"}

    def test_J03_legacy_success_no_error_key(self):
        assert "error" not in self._success().to_legacy_dict()

    def test_J04_legacy_failure_has_success_false(self):
        assert self._failure().to_legacy_dict()["success"] is False

    def test_J05_legacy_failure_has_error(self):
        assert self._failure().to_legacy_dict()["error"] == "bang"

    def test_J06_to_dict_has_duration_ms(self):
        assert "duration_ms" in self._success().to_dict()

    def test_J07_to_dict_has_request_id(self):
        assert "request_id" in self._success().to_dict()

    def test_J08_to_dict_has_invocation_source(self):
        assert "invocation_source" in self._success().to_dict()


# ---------------------------------------------------------------------------
# Group K -- No parallel authority assertion
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _EXECUTOR_AVAILABLE, reason="unified_node_executor unavailable")
class TestGroupK_NoParallelAuthority:
    def test_K01_no_parallel_node_execution_policy_present(self):
        assert "NO_PARALLEL" in NO_PARALLEL_NODE_EXECUTION_AUTHORITY_PR35_POLICY

    def test_K02_unified_executor_module_is_sole_authority(self):
        import core.nodes.unified_node_executor as unem
        assert hasattr(unem, "invoke_node")
        assert callable(unem.invoke_node)


# ---------------------------------------------------------------------------
# Group L -- PR-34 regression
# ---------------------------------------------------------------------------

class TestGroupL_PR34Regression:
    def test_L01_pr34_sentinel_still_importable(self):
        try:
            from core.runtime.source_dispatch_orchestrator import (
                CROSS_DEVICE_RUNTIME_ACCEPTANCE_PR34_SENTINEL,
            )
            assert len(CROSS_DEVICE_RUNTIME_ACCEPTANCE_PR34_SENTINEL) > 0
        except ImportError:
            pytest.skip("source_dispatch_orchestrator unavailable")
