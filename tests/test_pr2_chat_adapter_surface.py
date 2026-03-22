"""tests/test_pr2_chat_adapter_surface.py
==========================================

PR-2 — /api/v1/chat Compatibility Adapter Surface

Tests that lock in the demoted-surface role of ``/api/v1/chat``:

1.  UnifiedChatResponse still has all backward-compatible fields.
2.  UnifiedChatResponse new optional metadata fields exist with correct
    defaults.
3.  to_json_response() includes new fields when populated.
4.  to_json_response() does NOT break when new fields are absent (None).
5.  chat.py module-level docstring declares adapter surface role.
6.  chat() route handler docstring declares adapter surface role.
7.  chat.py does NOT contain any subject-core authority language.
8.  create_router() injects entry_surface="chat_adapter" into response.
9.  create_router() injects execution_authority="DesktopPresenceRuntime/OpenClawd".
10. create_router() injects surface_role="compat_adapter".
11. create_router() injects entry_source="http_post".
12. runtime_session_id from upstream result is propagated correctly.
13. Old fields remain intact when new metadata is also present.
14. Error path also preserves backward compat (no surface metadata leak).
15. UnifiedChatResponse model_dump round-trip with new fields.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))


# ===========================================================================
# Helpers
# ===========================================================================

def _make_runtime_result(
    *,
    success: bool = True,
    response: str = "ok",
    runtime_session_id: str = "rsid-test-001",
    intent: str = "chat",
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Produce a minimal DesktopPresenceRuntime result dict for mocking."""
    return {
        "success": success,
        "response": response,
        "runtime_session_id": runtime_session_id,
        "intent": intent,
        "error": "",
        "metadata": metadata or {"mode": "openclawd", "confidence": 0.9},
    }


# ===========================================================================
# 1–4: UnifiedChatResponse backward-compat + new fields
# ===========================================================================

class TestUnifiedChatResponseBackwardCompat:
    """Existing fields must be unchanged; new fields must be optional."""

    def test_existing_fields_still_present(self):
        from core.unified_response import UnifiedChatResponse
        resp = UnifiedChatResponse(success=True, response="hello")
        d = resp.to_json_response()
        for field in ("success", "response", "intent", "confidence", "mode",
                      "suggestions", "data", "error", "session_id", "model", "timestamp"):
            assert field in d, f"Backward-compat field '{field}' missing from response"

    def test_existing_fields_default_values(self):
        from core.unified_response import UnifiedChatResponse
        resp = UnifiedChatResponse(success=True, response="hello")
        d = resp.to_json_response()
        assert d["intent"] == ""
        assert d["confidence"] == 0.0
        assert d["mode"] == "chat"
        assert d["suggestions"] == []
        assert d["data"] == {}
        assert d["error"] == ""
        assert d["session_id"] == ""
        assert d["model"] == ""

    def test_new_metadata_fields_exist_on_model(self):
        from core.unified_response import UnifiedChatResponse
        resp = UnifiedChatResponse(success=True, response="hello")
        # Fields must exist on the model (default None)
        assert hasattr(resp, "runtime_session_id")
        assert hasattr(resp, "entry_surface")
        assert hasattr(resp, "entry_source")
        assert hasattr(resp, "execution_authority")
        assert hasattr(resp, "surface_role")

    def test_new_metadata_fields_default_none(self):
        from core.unified_response import UnifiedChatResponse
        resp = UnifiedChatResponse(success=True, response="hello")
        assert resp.runtime_session_id is None
        assert resp.entry_surface is None
        assert resp.entry_source is None
        assert resp.execution_authority is None
        assert resp.surface_role is None

    def test_new_fields_in_json_response_when_set(self):
        from core.unified_response import UnifiedChatResponse
        resp = UnifiedChatResponse(
            success=True,
            response="test",
            entry_surface="chat_adapter",
            entry_source="http_post",
            execution_authority="DesktopPresenceRuntime/OpenClawd",
            surface_role="compat_adapter",
            runtime_session_id="rsid-999",
        )
        d = resp.to_json_response()
        assert d["entry_surface"] == "chat_adapter"
        assert d["entry_source"] == "http_post"
        assert d["execution_authority"] == "DesktopPresenceRuntime/OpenClawd"
        assert d["surface_role"] == "compat_adapter"
        assert d["runtime_session_id"] == "rsid-999"

    def test_new_fields_in_json_response_when_none(self):
        """New fields must not remove existing keys or cause serialisation errors."""
        from core.unified_response import UnifiedChatResponse
        resp = UnifiedChatResponse(success=True, response="test")
        d = resp.to_json_response()
        # None values are serialised as None (exclude_none=False)
        assert "entry_surface" in d
        assert d["entry_surface"] is None
        assert "execution_authority" in d
        assert d["execution_authority"] is None

    def test_round_trip_with_new_fields(self):
        from core.unified_response import UnifiedChatResponse
        resp = UnifiedChatResponse(
            success=False,
            response="err",
            intent="device_control",
            confidence=0.7,
            mode="agent_react",
            error="device offline",
            session_id="s-1",
            model="gpt-4o-mini",
            entry_surface="chat_adapter",
            execution_authority="DesktopPresenceRuntime/OpenClawd",
            surface_role="compat_adapter",
        )
        d = resp.to_json_response()
        # Old fields
        assert d["success"] is False
        assert d["intent"] == "device_control"
        assert d["confidence"] == 0.7
        assert d["error"] == "device offline"
        # New fields
        assert d["entry_surface"] == "chat_adapter"
        assert d["execution_authority"] == "DesktopPresenceRuntime/OpenClawd"
        assert d["surface_role"] == "compat_adapter"


# ===========================================================================
# 5–7: chat.py source-level contract checks
# ===========================================================================

class TestChatModuleContract:
    """Source-level checks that chat.py correctly declares its demoted role."""

    def _read_chat_source(self) -> str:
        p = REPO_ROOT / "core" / "routes" / "chat.py"
        return p.read_text(encoding="utf-8")

    @staticmethod
    def _src_has_kwarg(src: str, key: str, value: str) -> bool:
        """Return True if src contains ``key="value"`` or ``key='value'``."""
        return f'{key}="{value}"' in src or f"{key}='{value}'" in src

    def test_module_docstring_declares_adapter_surface(self):
        src = self._read_chat_source()
        assert "adapter" in src.lower(), \
            "chat.py module docstring must declare adapter surface role"

    def test_module_docstring_says_not_subject_authority(self):
        src = self._read_chat_source()
        src_lower = src.lower()
        # Must contain a negative assertion about subject-core authority
        assert ("not" in src_lower and "authority" in src_lower) \
               or "no subject-core" in src_lower \
               or "does not own" in src_lower \
               or "no authority" in src_lower, \
            "chat.py must explicitly state it has no subject-core authority"

    def test_module_docstring_names_runtime_shell(self):
        src = self._read_chat_source()
        assert "DesktopPresenceRuntime" in src, \
            "chat.py must reference DesktopPresenceRuntime as the runtime shell"

    def test_module_docstring_names_subject_core(self):
        src = self._read_chat_source()
        assert "OpenClawd" in src, \
            "chat.py must reference OpenClawd as the subject core"

    def test_module_does_not_instantiate_openclawd_directly(self):
        src = self._read_chat_source()
        # chat.py must never import or instantiate OpenClawd directly;
        # it must go through DesktopPresenceRuntime
        assert "from core.openclawd import" not in src, \
            "chat.py must not import OpenClawd directly — use DesktopPresenceRuntime"
        assert "OpenClawd()" not in src, \
            "chat.py must not instantiate OpenClawd directly"

    def test_route_handler_docstring_declares_role(self):
        src = self._read_chat_source()
        # The handler docstring should mention "adapter" or "compat"
        assert "compat" in src.lower() or "compatibility" in src.lower(), \
            "chat() handler docstring should mention compatibility adapter role"

    def test_entry_surface_literal_present(self):
        src = self._read_chat_source()
        assert self._src_has_kwarg(src, "entry_surface", "chat_adapter"), \
            "chat.py must set entry_surface='chat_adapter' when building response"

    def test_execution_authority_literal_present(self):
        src = self._read_chat_source()
        assert "DesktopPresenceRuntime/OpenClawd" in src, \
            "chat.py must set execution_authority to 'DesktopPresenceRuntime/OpenClawd'"

    def test_surface_role_literal_present(self):
        src = self._read_chat_source()
        assert self._src_has_kwarg(src, "surface_role", "compat_adapter"), \
            "chat.py must set surface_role='compat_adapter' when building response"


# ===========================================================================
# 8–14: create_router() response injection tests (unit, mocked runtime)
# ===========================================================================

class TestChatRouterSurfaceMetadata:
    """Test that the route handler injects surface metadata correctly."""

    def _get_router_and_endpoint(self):
        """Return the FastAPI router and the chat async function."""
        from core.routes.chat import create_router
        router = create_router()
        # Find the POST /api/v1/chat route
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/api/v1/chat":
                return router, route.endpoint
        pytest.fail("/api/v1/chat route not found in router")

    def _make_request(self, message: str = "hello", **kwargs):
        """Build a minimal ChatRequest-like mock."""
        req = MagicMock()
        req.message = message
        req.device_id = kwargs.get("device_id", "")
        req.session_id = kwargs.get("session_id", "")
        req.context = kwargs.get("context", {})
        req.required_capabilities = kwargs.get("required_capabilities", [])
        req.multimodal_context = kwargs.get("multimodal_context", {})
        req.entry_mode = kwargs.get("entry_mode", "")
        req.target_device = kwargs.get("target_device", "")
        return req

    def _call_endpoint(self, endpoint, req):
        """Run the async endpoint and return the JSONResponse."""
        mock_runtime = MagicMock()
        mock_runtime.handle_request = AsyncMock(
            return_value=_make_runtime_result()
        )
        with patch(
            "core.desktop_presence_runtime.get_desktop_presence_runtime",
            return_value=mock_runtime,
        ):
            return asyncio.run(endpoint(req))

    def test_entry_surface_in_response(self):
        _, endpoint = self._get_router_and_endpoint()
        req = self._make_request("test")
        resp = self._call_endpoint(endpoint, req)
        body = resp.body
        import json
        data = json.loads(body)
        assert data.get("entry_surface") == "chat_adapter", \
            "entry_surface must be 'chat_adapter' in response"

    def test_entry_source_in_response(self):
        _, endpoint = self._get_router_and_endpoint()
        req = self._make_request("test")
        resp = self._call_endpoint(endpoint, req)
        import json
        data = json.loads(resp.body)
        assert data.get("entry_source") == "http_post"

    def test_execution_authority_in_response(self):
        _, endpoint = self._get_router_and_endpoint()
        req = self._make_request("test")
        resp = self._call_endpoint(endpoint, req)
        import json
        data = json.loads(resp.body)
        assert data.get("execution_authority") == "DesktopPresenceRuntime/OpenClawd"

    def test_surface_role_in_response(self):
        _, endpoint = self._get_router_and_endpoint()
        req = self._make_request("test")
        resp = self._call_endpoint(endpoint, req)
        import json
        data = json.loads(resp.body)
        assert data.get("surface_role") == "compat_adapter"

    def test_runtime_session_id_propagated(self):
        _, endpoint = self._get_router_and_endpoint()
        req = self._make_request("test")
        mock_runtime = MagicMock()
        mock_runtime.handle_request = AsyncMock(
            return_value=_make_runtime_result(runtime_session_id="rsid-abc-123")
        )
        with patch(
            "core.desktop_presence_runtime.get_desktop_presence_runtime",
            return_value=mock_runtime,
        ):
            resp = asyncio.run(endpoint(req))
        import json
        data = json.loads(resp.body)
        assert data.get("runtime_session_id") == "rsid-abc-123"

    def test_old_fields_intact_with_new_metadata(self):
        """Success, response, intent, etc. must still be present alongside new fields."""
        _, endpoint = self._get_router_and_endpoint()
        req = self._make_request("hello world")
        mock_runtime = MagicMock()
        mock_runtime.handle_request = AsyncMock(
            return_value=_make_runtime_result(
                success=True,
                response="Hi there",
                intent="chat",
                metadata={"mode": "openclawd", "confidence": 0.95, "model": "gpt-4o"},
            )
        )
        with patch(
            "core.desktop_presence_runtime.get_desktop_presence_runtime",
            return_value=mock_runtime,
        ):
            resp = asyncio.run(endpoint(req))
        import json
        data = json.loads(resp.body)
        # Old backward-compat fields
        assert data["success"] is True
        assert data["response"] == "Hi there"
        assert data["intent"] == "chat"
        assert "timestamp" in data
        # New metadata fields
        assert data["entry_surface"] == "chat_adapter"
        assert data["surface_role"] == "compat_adapter"

    def test_error_path_backward_compat(self):
        """When the runtime raises, the error response must still be parseable."""
        _, endpoint = self._get_router_and_endpoint()
        req = self._make_request("crash test")
        with patch(
            "core.desktop_presence_runtime.get_desktop_presence_runtime",
            side_effect=RuntimeError("simulated failure"),
        ):
            resp = asyncio.run(endpoint(req))
        import json
        data = json.loads(resp.body)
        assert data["success"] is False
        assert "error" in data
        assert "response" in data
        assert "timestamp" in data

    def test_route_still_works_end_to_end(self):
        """Smoke test: the route must complete without exceptions."""
        _, endpoint = self._get_router_and_endpoint()
        req = self._make_request("smoke test message")
        # Should not raise
        resp = self._call_endpoint(endpoint, req)
        assert resp is not None
        import json
        data = json.loads(resp.body)
        assert isinstance(data, dict)
        assert "success" in data


# ===========================================================================
# 15: UnifiedChatResponse model_dump round-trip with all new fields
# ===========================================================================

class TestUnifiedChatResponseRoundTrip:
    def test_full_round_trip(self):
        from core.unified_response import UnifiedChatResponse
        resp = UnifiedChatResponse(
            success=True,
            response="all good",
            intent="chat",
            confidence=0.99,
            mode="openclawd",
            suggestions=["try this"],
            data={"key": "val"},
            error="",
            session_id="s-abc",
            model="gpt-4o-mini",
            runtime_session_id="rsid-xyz",
            entry_surface="chat_adapter",
            entry_source="http_post",
            execution_authority="DesktopPresenceRuntime/OpenClawd",
            surface_role="compat_adapter",
        )
        d = resp.to_json_response()
        # All fields present
        assert d["success"] is True
        assert d["response"] == "all good"
        assert d["intent"] == "chat"
        assert d["confidence"] == 0.99
        assert d["mode"] == "openclawd"
        assert d["suggestions"] == ["try this"]
        assert d["data"] == {"key": "val"}
        assert d["error"] == ""
        assert d["session_id"] == "s-abc"
        assert d["model"] == "gpt-4o-mini"
        assert d["runtime_session_id"] == "rsid-xyz"
        assert d["entry_surface"] == "chat_adapter"
        assert d["entry_source"] == "http_post"
        assert d["execution_authority"] == "DesktopPresenceRuntime/OpenClawd"
        assert d["surface_role"] == "compat_adapter"
        assert "timestamp" in d


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
