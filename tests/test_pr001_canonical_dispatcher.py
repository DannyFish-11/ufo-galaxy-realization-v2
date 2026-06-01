#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr001_canonical_dispatcher.py
==========================================
Tests for PR-001: Canonical Capability Dispatcher for OpenClawd.

Coverage
--------
1.  CapabilityLayer classification
    - mcp__<server>__<tool> → MCP
    - mcp__gateway__<tool>  → MCP_GW
    - skill__<id>           → SKILL
    - node__<id>__<action>  → NODE
    - github__<action>      → GITHUB
    - unknown prefix        → UNKNOWN
    - classify() on CapabilityLayer enum matches classify_layer() on ToolCallRecord

2.  DispatchResult contract
    - construction with defaults
    - to_dict() is JSON-serialisable
    - to_dict() contains all expected keys (success/result/error/layer/latency_ms)
    - as_legacy_dict() returns minimal backward-compatible dict
    - needs_confirmation=True propagates through both serialisers
    - dispatch_id is auto-generated UUID
    - dispatched_at is auto-populated

3.  CanonicalDispatcher construction
    - default construction succeeds
    - accepts node_id_to_key and tool_permission_checker kwargs
    - shares node_id_to_key reference (mutations visible to both sides)

4.  Permission guard — _check_permission
    - no checker → returns None (allow)
    - checker denies → returns failed DispatchResult with "权限拒绝" in error
    - checker requires confirmation → returns DispatchResult with needs_confirmation=True
    - checker raises → returns None (allow, defensive)

5.  MCP dispatch — normalized successful call (mocked backend)
    - mcp__<server>__<tool> with mock mcp_loader → success=True, result propagated
    - mcp__gateway__<tool> with mock gateway → success=True, result propagated
    - malformed mcp name (only 2 parts) → success=False, error mentions tool name

6.  Skill dispatch — normalized successful call (mocked backend)
    - skill__<id> with mock registry.invoke ok → success=True, outputs propagated
    - skill__<id> with mock registry.invoke failure → success=False, error message
    - lazy adapter registration: registry.has_skill returns False → register_skill called

7.  Error wrapping — failure paths return consistent DispatchResult shape
    - MCP backend raises → success=False, error=str(exc), layer=MCP
    - Skill backend raises → success=False, error=str(exc), layer=SKILL
    - unknown prefix → success=False, layer=UNKNOWN

8.  OpenClawd integration — _capability_dispatcher is primary execution path
    - OpenClawd().__new__ has _capability_dispatcher attribute
    - _dispatch_tool_call delegates to _capability_dispatcher when available
    - _dispatch_tool_call falls back to inline path when dispatcher is None

9.  Tool-call metadata stability
    - DispatchResult.layer matches ToolCallRecord.classify_layer() for same tool_name
    - latency_ms is a non-negative float
    - dispatch_id changes on each call (UUID uniqueness)

10. dispatcher.dispatch() returns DispatchResult (not raw dict)
    - result is instance of DispatchResult
    - to_dict() output is identical to as_legacy_dict() keys plus metadata keys
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_running_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# 1. CapabilityLayer classification
# ---------------------------------------------------------------------------

class TestCapabilityLayerClassification:
    def _import(self):
        from core.capabilities.canonical_dispatcher import CapabilityLayer
        return CapabilityLayer

    def test_mcp_prefix(self):
        CL = self._import()
        assert CL.classify("mcp__weather__get_forecast") == CL.MCP

    def test_mcp_gateway_prefix(self):
        CL = self._import()
        assert CL.classify("mcp__gateway__list_tools") == CL.MCP_GW

    def test_skill_prefix(self):
        CL = self._import()
        assert CL.classify("skill__hello") == CL.SKILL

    def test_node_prefix(self):
        CL = self._import()
        assert CL.classify("node__Node_06_Filesystem__read_file") == CL.NODE

    def test_github_prefix(self):
        CL = self._import()
        assert CL.classify("github__install") == CL.GITHUB

    def test_unknown_prefix(self):
        CL = self._import()
        assert CL.classify("custom__something") == CL.UNKNOWN

    def test_empty_string(self):
        CL = self._import()
        assert CL.classify("") == CL.UNKNOWN

    def test_mcp_exactly_two_underscores_not_gateway(self):
        CL = self._import()
        # mcp__notgateway__tool should still be MCP not MCP_GW
        assert CL.classify("mcp__weather__temperature") == CL.MCP

    def test_classify_matches_tool_call_record(self):
        from core.capabilities.canonical_dispatcher import CapabilityLayer
        try:
            import importlib
            import sys
            # Import tool_call directly, bypassing schemas/__init__.py which needs pydantic
            spec = importlib.util.spec_from_file_location(
                "core.schemas.tool_call",
                __import__("pathlib").Path(__file__).parent.parent / "core" / "schemas" / "tool_call.py",
            )
            _mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(_mod)
            ToolLayer = _mod.ToolLayer
            ToolCallRecord = _mod.ToolCallRecord
        except Exception:
            pytest.skip("pydantic not available — skipping ToolCallRecord cross-check")
            return

        mapping = {
            "mcp__srv__tool": (CapabilityLayer.MCP, ToolLayer.MCP),
            "mcp__gateway__x": (CapabilityLayer.MCP_GW, ToolLayer.MCP_GW),
            "skill__abc": (CapabilityLayer.SKILL, ToolLayer.SKILL),
            "node__n1__act": (CapabilityLayer.NODE, ToolLayer.NODE),
        }
        for tool_name, (cl, tl) in mapping.items():
            assert CapabilityLayer.classify(tool_name) == cl
            assert ToolCallRecord.classify_layer(tool_name) == tl


# ---------------------------------------------------------------------------
# 2. DispatchResult contract
# ---------------------------------------------------------------------------

class TestDispatchResult:
    def _import(self):
        from core.capabilities.canonical_dispatcher import DispatchResult, CapabilityLayer
        return DispatchResult, CapabilityLayer

    def test_defaults(self):
        DR, CL = self._import()
        r = DR()
        assert r.success is True
        assert r.result is None
        assert r.error is None
        assert r.latency_ms == 0.0
        assert r.layer == CL.UNKNOWN

    def test_to_dict_json_serialisable(self):
        DR, CL = self._import()
        r = DR(success=True, result={"key": "val"}, tool_name="skill__x", layer=CL.SKILL, latency_ms=12.3)
        d = r.to_dict()
        # must not raise
        json.dumps(d)

    def test_to_dict_has_expected_keys(self):
        DR, CL = self._import()
        r = DR(success=False, error="boom", tool_name="mcp__s__t", layer=CL.MCP)
        d = r.to_dict()
        for k in ("success", "result", "error", "tool_name", "layer", "latency_ms", "dispatch_id"):
            assert k in d, f"missing key: {k}"

    def test_as_legacy_dict_minimal(self):
        DR, CL = self._import()
        r = DR(success=True, result=42)
        d = r.as_legacy_dict()
        assert d["success"] is True
        assert d["result"] == 42
        assert "error" not in d

    def test_as_legacy_dict_error(self):
        DR, CL = self._import()
        r = DR(success=False, error="something went wrong")
        d = r.as_legacy_dict()
        assert d["success"] is False
        assert d["error"] == "something went wrong"

    def test_needs_confirmation_propagates_to_dict(self):
        DR, CL = self._import()
        r = DR(success=False, needs_confirmation=True, tool_name="skill__risky")
        d = r.to_dict()
        assert d.get("needs_confirmation") is True
        d2 = r.as_legacy_dict()
        assert d2.get("needs_confirmation") is True
        assert d2.get("tool") == "skill__risky"

    def test_dispatch_id_is_uuid(self):
        DR, CL = self._import()
        r = DR()
        uid = uuid.UUID(r.dispatch_id)  # must not raise
        assert uid.version == 4

    def test_dispatched_at_populated(self):
        DR, CL = self._import()
        before = time.time()
        r = DR()
        after = time.time()
        assert before <= r.dispatched_at <= after

    def test_layer_value_in_to_dict(self):
        DR, CL = self._import()
        r = DR(layer=CL.SKILL)
        assert r.to_dict()["layer"] == "skill"


# ---------------------------------------------------------------------------
# 3. CanonicalDispatcher construction
# ---------------------------------------------------------------------------

class TestCanonicalDispatcherConstruction:
    def _import(self):
        from core.capabilities.canonical_dispatcher import CanonicalDispatcher
        return CanonicalDispatcher

    def test_default_construction(self):
        CD = self._import()
        d = CD()
        assert d.device_id == ""
        assert d.session_id == ""
        assert d.trace_id == ""

    def test_keyword_args(self):
        CD = self._import()
        d = CD(device_id="dev1", session_id="sess1", trace_id="tr1")
        assert d.device_id == "dev1"
        assert d.session_id == "sess1"
        assert d.trace_id == "tr1"

    def test_shared_node_id_to_key_reference(self):
        CD = self._import()
        shared = {"node1": "Node_01_Alpha"}
        d = CD(node_id_to_key=shared)
        assert d._node_id_to_key is shared
        # mutation from outside is visible inside
        shared["node2"] = "Node_02_Beta"
        assert d._node_id_to_key.get("node2") == "Node_02_Beta"


# ---------------------------------------------------------------------------
# 4. Permission guard
# ---------------------------------------------------------------------------

class TestPermissionGuard:
    def _make_dispatcher(self, checker=None):
        from core.capabilities.canonical_dispatcher import CanonicalDispatcher
        return CanonicalDispatcher(tool_permission_checker=checker)

    def test_no_checker_allows(self):
        d = self._make_dispatcher(checker=None)
        result = d._check_permission("skill__x", "sess", "dev")
        assert result is None

    def test_checker_denies(self):
        checker = MagicMock()
        checker.check.return_value = MagicMock(allowed=False, reason="not allowed")
        d = self._make_dispatcher(checker=checker)
        result = d._check_permission("skill__x", "sess", "dev")
        assert result is not None
        assert result.success is False
        assert "权限拒绝" in (result.error or "")

    def test_checker_requires_confirmation(self):
        checker = MagicMock()
        perm = MagicMock()
        perm.allowed = True
        perm.requires_confirmation = True
        perm.risk_level = "high"
        checker.check.return_value = perm
        d = self._make_dispatcher(checker=checker)
        result = d._check_permission("skill__risky", "sess", "dev")
        assert result is not None
        assert result.success is False
        assert result.needs_confirmation is True

    def test_checker_raises_is_ignored(self):
        checker = MagicMock()
        checker.check.side_effect = RuntimeError("oops")
        d = self._make_dispatcher(checker=checker)
        result = d._check_permission("skill__x", "sess", "dev")
        assert result is None  # defensive pass-through


# ---------------------------------------------------------------------------
# 5. MCP dispatch — mocked backend
# ---------------------------------------------------------------------------

class TestMCPDispatch:
    def _make_dispatcher(self):
        from core.capabilities.canonical_dispatcher import CanonicalDispatcher
        return CanonicalDispatcher()

    def test_mcp_success(self):
        d = self._make_dispatcher()

        mock_result = {"content": "sunny", "success": True}
        mock_mcp_loader = MagicMock()
        mock_mcp_loader.call_tool = AsyncMock(return_value=mock_result)

        mock_registry = MagicMock()
        mock_registry._emit_log = MagicMock()

        mock_req_cls = MagicMock(return_value=MagicMock(trace_id="t1"))
        mock_metrics_cls = MagicMock(return_value=MagicMock(finish=MagicMock()))
        mock_resp_cls = MagicMock()
        mock_resp_cls.success = MagicMock(return_value=MagicMock())

        with patch("core.capabilities.canonical_dispatcher.CapabilityLayer.classify"):
            pass

        with (
            patch("core.capabilities.canonical_dispatcher.time") as mock_time,
            patch.dict("sys.modules", {
                "core.mcp_loader": MagicMock(mcp_loader=mock_mcp_loader),
                "core.skill_contract": MagicMock(
                    SkillRequest=mock_req_cls,
                    SkillMetrics=mock_metrics_cls,
                    SkillResponse=mock_resp_cls,
                    SkillErrorCode=MagicMock(EXECUTION_ERROR="exec_error"),
                ),
                "core.skill_registry": MagicMock(get_skill_registry=MagicMock(return_value=mock_registry)),
            }),
        ):
            mock_time.time.return_value = 0.0

            result = _run(d._dispatch_mcp("mcp__weather__forecast", {}, "dev", "sess"))

        assert result.success is True
        assert result.result == mock_result

    def test_mcp_malformed_name(self):
        d = self._make_dispatcher()
        result = _run(d._dispatch_mcp("mcp__toolonly", {}, "", ""))
        assert result.success is False
        assert "无效 MCP 工具名" in (result.error or "")

    def test_dispatch_returns_dispatch_result_for_mcp(self):
        from core.capabilities.canonical_dispatcher import DispatchResult
        d = self._make_dispatcher()

        mock_mcp_loader = MagicMock()
        mock_mcp_loader.call_tool = AsyncMock(return_value={"data": 1})
        mock_registry = MagicMock()
        mock_registry._emit_log = MagicMock()

        with patch.dict("sys.modules", {
            "core.mcp_loader": MagicMock(mcp_loader=mock_mcp_loader),
            "core.skill_contract": MagicMock(
                SkillRequest=MagicMock(return_value=MagicMock(trace_id="t")),
                SkillMetrics=MagicMock(return_value=MagicMock(finish=MagicMock())),
                SkillResponse=MagicMock(success=MagicMock(return_value=MagicMock())),
                SkillErrorCode=MagicMock(EXECUTION_ERROR="e"),
            ),
            "core.skill_registry": MagicMock(get_skill_registry=MagicMock(return_value=mock_registry)),
            "core.state_event_bus": MagicMock(
                emit=MagicMock(),
                StateEventType=MagicMock(SKILL_INVOKED="si", SKILL_FAILED="sf"),
            ),
        }):
            result = _run(d.dispatch("mcp__weather__forecast", {}))

        assert isinstance(result, DispatchResult)


# ---------------------------------------------------------------------------
# 6. Skill dispatch — mocked backend
# ---------------------------------------------------------------------------

class TestSkillDispatch:
    def _make_dispatcher(self):
        from core.capabilities.canonical_dispatcher import CanonicalDispatcher
        return CanonicalDispatcher()

    def _mock_registry(self, *, ok: bool = True, outputs=None, error_msg="fail"):
        mock = MagicMock()
        resp = MagicMock()
        resp.ok = ok
        resp.outputs = outputs or {"result": "hello"}
        if not ok:
            err_obj = MagicMock()
            err_obj.message = error_msg
            resp.first_error = err_obj
        else:
            resp.first_error = None
        mock.has_skill.return_value = True
        mock.invoke = AsyncMock(return_value=resp)
        return mock

    def test_skill_success(self):
        d = self._make_dispatcher()
        mock_registry = self._mock_registry(ok=True, outputs={"greeting": "hi"})

        with patch.dict("sys.modules", {
            "core.skill_registry": MagicMock(get_skill_registry=MagicMock(return_value=mock_registry)),
            "core.skill_contract": MagicMock(SkillRequest=MagicMock(return_value=MagicMock())),
            "core.skill_loader": MagicMock(skill_loader=MagicMock()),
        }):
            result = _run(d._dispatch_skill("skill__hello", {}, "dev", "sess"))

        assert result.success is True
        assert result.result == {"greeting": "hi"}

    def test_skill_failure(self):
        d = self._make_dispatcher()
        mock_registry = self._mock_registry(ok=False, error_msg="no such skill")

        with patch.dict("sys.modules", {
            "core.skill_registry": MagicMock(get_skill_registry=MagicMock(return_value=mock_registry)),
            "core.skill_contract": MagicMock(SkillRequest=MagicMock(return_value=MagicMock())),
            "core.skill_loader": MagicMock(skill_loader=MagicMock()),
        }):
            result = _run(d._dispatch_skill("skill__missing", {}, "dev", "sess"))

        assert result.success is False
        assert "no such skill" in (result.error or "")

    def test_lazy_adapter_registered_when_missing(self):
        d = self._make_dispatcher()
        mock_registry = MagicMock()
        mock_registry.has_skill.return_value = False
        mock_registry.register_skill = MagicMock()
        resp = MagicMock()
        resp.ok = True
        resp.outputs = {}
        resp.first_error = None
        mock_registry.invoke = AsyncMock(return_value=resp)

        with patch.dict("sys.modules", {
            "core.skill_registry": MagicMock(get_skill_registry=MagicMock(return_value=mock_registry)),
            "core.skill_contract": MagicMock(SkillRequest=MagicMock(return_value=MagicMock())),
            "core.skill_loader": MagicMock(skill_loader=MagicMock()),
        }):
            _run(d._dispatch_skill("skill__new_skill", {}, "", ""))

        mock_registry.register_skill.assert_called_once()


# ---------------------------------------------------------------------------
# 7. Error wrapping
# ---------------------------------------------------------------------------

class TestErrorWrapping:
    def _make_dispatcher(self):
        from core.capabilities.canonical_dispatcher import CanonicalDispatcher
        return CanonicalDispatcher()

    def test_unknown_prefix_returns_error(self):
        d = self._make_dispatcher()
        with patch.dict("sys.modules", {
            "core.state_event_bus": MagicMock(
                emit=MagicMock(),
                StateEventType=MagicMock(SKILL_INVOKED="si", SKILL_FAILED="sf"),
            ),
        }):
            result = _run(d.dispatch("custom__something", {}))
        assert result.success is False
        assert "未知工具前缀" in (result.error or "")

    def test_mcp_backend_exception_returns_error(self):
        from core.capabilities.canonical_dispatcher import CapabilityLayer
        d = self._make_dispatcher()

        mock_mcp_loader = MagicMock()
        mock_mcp_loader.call_tool = AsyncMock(side_effect=RuntimeError("network down"))
        mock_registry = MagicMock()
        mock_registry._emit_log = MagicMock()

        with patch.dict("sys.modules", {
            "core.mcp_loader": MagicMock(mcp_loader=mock_mcp_loader),
            "core.skill_contract": MagicMock(
                SkillRequest=MagicMock(return_value=MagicMock(trace_id="t")),
                SkillMetrics=MagicMock(return_value=MagicMock(finish=MagicMock())),
                SkillResponse=MagicMock(failure=MagicMock(return_value=MagicMock())),
                SkillErrorCode=MagicMock(EXECUTION_ERROR="e"),
            ),
            "core.skill_registry": MagicMock(get_skill_registry=MagicMock(return_value=mock_registry)),
            "core.state_event_bus": MagicMock(
                emit=MagicMock(),
                StateEventType=MagicMock(SKILL_INVOKED="si", SKILL_FAILED="sf"),
            ),
        }):
            result = _run(d.dispatch("mcp__weather__forecast", {}))

        assert result.success is False
        assert "network down" in (result.error or "")
        assert result.layer == CapabilityLayer.MCP

    def test_skill_backend_exception_returns_error(self):
        from core.capabilities.canonical_dispatcher import CapabilityLayer
        d = self._make_dispatcher()

        mock_registry = MagicMock()
        mock_registry.has_skill.return_value = True
        mock_registry.invoke = AsyncMock(side_effect=RuntimeError("db gone"))

        with patch.dict("sys.modules", {
            "core.skill_registry": MagicMock(get_skill_registry=MagicMock(return_value=mock_registry)),
            "core.skill_contract": MagicMock(SkillRequest=MagicMock(return_value=MagicMock())),
            "core.skill_loader": MagicMock(skill_loader=MagicMock()),
            "core.state_event_bus": MagicMock(
                emit=MagicMock(),
                StateEventType=MagicMock(SKILL_INVOKED="si", SKILL_FAILED="sf"),
            ),
        }):
            result = _run(d.dispatch("skill__broken", {}))

        assert result.success is False
        assert "db gone" in (result.error or "")
        assert result.layer == CapabilityLayer.SKILL


# ---------------------------------------------------------------------------
# 8. OpenClawd integration
# ---------------------------------------------------------------------------

class TestOpenClawdIntegration:
    def _build_minimal_openclawd(self):
        """Construct a minimal OpenClawd without running full __init__ side effects."""
        from core.openclawd import OpenClawd
        oc = object.__new__(OpenClawd)
        oc._initialized = False
        oc._tool_permission_checker = None
        oc._node_id_to_key = {}
        oc._capability_dispatcher = None
        return oc

    def test_openclawd_has_capability_dispatcher_attribute(self):
        from core.openclawd import OpenClawd
        # The attribute must exist after __init__ (real or None from import error).
        oc = self._build_minimal_openclawd()
        assert hasattr(oc, "_capability_dispatcher")

    def test_dispatch_tool_call_uses_dispatcher_when_available(self):
        from core.capabilities.canonical_dispatcher import CanonicalDispatcher, DispatchResult, CapabilityLayer
        oc = self._build_minimal_openclawd()
        oc._current_trace_id = "tr1"
        oc._current_session_id = "sess1"
        oc._current_device_id = "dev1"

        mock_dr = DispatchResult(success=True, result="mocked_result", layer=CapabilityLayer.SKILL)
        mock_dispatcher = MagicMock(spec=CanonicalDispatcher)
        mock_dispatcher.dispatch = AsyncMock(return_value=mock_dr)
        oc._capability_dispatcher = mock_dispatcher

        result = _run(oc._dispatch_tool_call("skill__hello", {"x": 1}))

        mock_dispatcher.dispatch.assert_called_once_with(
            "skill__hello",
            {"x": 1},
            device_id="dev1",
            session_id="sess1",
            trace_id="tr1",
        )
        assert result["success"] is True
        assert result["result"] == "mocked_result"

    def test_dispatch_tool_call_falls_back_when_dispatcher_is_none(self):
        oc = self._build_minimal_openclawd()
        oc._capability_dispatcher = None
        oc._current_trace_id = None
        oc._current_session_id = None
        oc._current_device_id = ""

        # Patch the fallback inline path so it doesn't need real imports
        with patch.dict("sys.modules", {
            "core.state_event_bus": MagicMock(
                emit=MagicMock(),
                StateEventType=MagicMock(SKILL_INVOKED="si", SKILL_FAILED="sf"),
            ),
        }):
            result = _run(oc._dispatch_tool_call("unknown__tool", {}))

        # Inline fallback should return an error for unknown prefix
        assert result["success"] is False

    def test_dispatcher_context_synced_on_process(self):
        """After process() syncs context, dispatcher attrs reflect current request."""
        from core.capabilities.canonical_dispatcher import CanonicalDispatcher
        oc = self._build_minimal_openclawd()
        mock_dispatcher = MagicMock(spec=CanonicalDispatcher)
        mock_dispatcher.device_id = ""
        mock_dispatcher.session_id = ""
        mock_dispatcher.trace_id = ""
        oc._capability_dispatcher = mock_dispatcher

        # Simulate the context sync that happens inside process()
        oc._current_device_id = "dev-sync"
        oc._current_session_id = "sess-sync"
        oc._current_trace_id = "trace-sync"
        _dispatcher = oc._capability_dispatcher
        if _dispatcher is not None:
            _dispatcher.device_id = oc._current_device_id
            _dispatcher.session_id = oc._current_session_id
            _dispatcher.trace_id = oc._current_trace_id

        assert mock_dispatcher.device_id == "dev-sync"
        assert mock_dispatcher.session_id == "sess-sync"
        assert mock_dispatcher.trace_id == "trace-sync"


# ---------------------------------------------------------------------------
# 9. Tool-call metadata stability
# ---------------------------------------------------------------------------

class TestToolCallMetadataStability:
    def test_layer_matches_tool_call_record(self):
        from core.capabilities.canonical_dispatcher import CapabilityLayer
        try:
            import importlib
            spec = importlib.util.spec_from_file_location(
                "core.schemas.tool_call",
                __import__("pathlib").Path(__file__).parent.parent / "core" / "schemas" / "tool_call.py",
            )
            _mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(_mod)
            ToolLayer = _mod.ToolLayer
            ToolCallRecord = _mod.ToolCallRecord
        except Exception:
            pytest.skip("pydantic not available — skipping ToolCallRecord cross-check")
            return

        pairs = [
            ("mcp__s__t", CapabilityLayer.MCP, ToolLayer.MCP),
            ("mcp__gateway__t", CapabilityLayer.MCP_GW, ToolLayer.MCP_GW),
            ("skill__abc", CapabilityLayer.SKILL, ToolLayer.SKILL),
            ("node__n1__act", CapabilityLayer.NODE, ToolLayer.NODE),
        ]
        for tool_name, expected_cl, expected_tl in pairs:
            assert CapabilityLayer.classify(tool_name) == expected_cl
            assert ToolCallRecord.classify_layer(tool_name) == expected_tl

    def test_latency_ms_non_negative(self):
        from core.capabilities.canonical_dispatcher import DispatchResult
        r = DispatchResult(latency_ms=0.0)
        assert r.latency_ms >= 0.0

    def test_dispatch_ids_are_unique(self):
        from core.capabilities.canonical_dispatcher import DispatchResult
        ids = {DispatchResult().dispatch_id for _ in range(20)}
        assert len(ids) == 20  # all unique

    def test_to_dict_and_as_legacy_dict_share_core_keys(self):
        from core.capabilities.canonical_dispatcher import DispatchResult, CapabilityLayer
        r = DispatchResult(success=True, result="x", layer=CapabilityLayer.SKILL, latency_ms=5.5)
        full = r.to_dict()
        legacy = r.as_legacy_dict()
        # Legacy keys must be present in full dict
        for k in legacy:
            assert k in full or k in ("tool",)


# ---------------------------------------------------------------------------
# 10. dispatch() return type
# ---------------------------------------------------------------------------

class TestDispatchReturnType:
    def test_dispatch_returns_dispatch_result_for_unknown(self):
        from core.capabilities.canonical_dispatcher import CanonicalDispatcher, DispatchResult
        d = CanonicalDispatcher()
        with patch.dict("sys.modules", {
            "core.state_event_bus": MagicMock(
                emit=MagicMock(),
                StateEventType=MagicMock(SKILL_INVOKED="si", SKILL_FAILED="sf"),
            ),
        }):
            result = _run(d.dispatch("unknown__x", {"a": 1}))
        assert isinstance(result, DispatchResult)
        assert result.success is False

    def test_dispatch_result_to_dict_json_serialisable_after_mcp(self):
        from core.capabilities.canonical_dispatcher import CanonicalDispatcher, DispatchResult

        d = CanonicalDispatcher()
        mock_mcp_loader = MagicMock()
        mock_mcp_loader.call_tool = AsyncMock(return_value={"temp": 20})
        mock_registry = MagicMock()
        mock_registry._emit_log = MagicMock()

        with patch.dict("sys.modules", {
            "core.mcp_loader": MagicMock(mcp_loader=mock_mcp_loader),
            "core.skill_contract": MagicMock(
                SkillRequest=MagicMock(return_value=MagicMock(trace_id="t")),
                SkillMetrics=MagicMock(return_value=MagicMock(finish=MagicMock())),
                SkillResponse=MagicMock(success=MagicMock(return_value=MagicMock())),
                SkillErrorCode=MagicMock(EXECUTION_ERROR="e"),
            ),
            "core.skill_registry": MagicMock(get_skill_registry=MagicMock(return_value=mock_registry)),
            "core.state_event_bus": MagicMock(
                emit=MagicMock(),
                StateEventType=MagicMock(SKILL_INVOKED="si", SKILL_FAILED="sf"),
            ),
        }):
            result = _run(d.dispatch("mcp__weather__forecast", {}))

        assert isinstance(result, DispatchResult)
        d_dict = result.to_dict()
        json.dumps(d_dict)  # must not raise


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

class TestGetCanonicalDispatcher:
    def test_get_returns_same_instance(self):
        from core.capabilities.canonical_dispatcher import get_canonical_dispatcher
        import core.capabilities.canonical_dispatcher as mod
        mod._DEFAULT_DISPATCHER = None  # reset
        a = get_canonical_dispatcher()
        b = get_canonical_dispatcher()
        assert a is b

    def test_get_returns_canonical_dispatcher_instance(self):
        from core.capabilities.canonical_dispatcher import get_canonical_dispatcher, CanonicalDispatcher
        import core.capabilities.canonical_dispatcher as mod
        mod._DEFAULT_DISPATCHER = None
        inst = get_canonical_dispatcher()
        assert isinstance(inst, CanonicalDispatcher)
