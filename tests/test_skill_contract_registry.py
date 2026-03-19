"""tests/test_skill_contract_registry.py
=========================================

Unit tests for :mod:`core.skill_contract` and :mod:`core.skill_registry`.

Test groups
-----------
  A) SkillErrorCode / is_retryable_error
  B) SkillRequest dataclass and validation helpers
  C) SkillResponse / SkillError data classes
  D) SkillMetrics timing
  E) SkillRegistry — registration / discovery
  F) SkillRegistry — sync and async handler invocation
  G) SkillRegistry — NOT_FOUND path
  H) SkillRegistry — INVALID_INPUT path (contract violation)
  I) SkillRegistry — EXECUTION_ERROR path (handler raises)
  J) SkillRegistry — TIMEOUT path
  K) SkillRegistry — permission denied (mocked checker)
  L) SkillRegistry — permission requires_confirmation
  M) SkillRegistry — permission checker raises (allow-by-default)
  N) SkillRegistry — observability log entries
  O) SkillRegistry — unregister_skill
  P) Singleton helpers (get_skill_registry / reset_skill_registry)
  Q) SkillResponse.to_dict() round-trip
  R) openclawd._dispatch_tool_call skill__ path routes through registry
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.skill_contract import (
    SkillError,
    SkillErrorCode,
    SkillMetrics,
    SkillRequest,
    SkillResponse,
    SkillStatus,
    is_retryable_error,
    validate_skill_request,
    validate_skill_response,
)
from core.skill_registry import (
    SkillEntry,
    SkillRegistry,
    get_skill_registry,
    reset_skill_registry,
)


# ===========================================================================
# Helpers
# ===========================================================================


def _fresh_registry() -> SkillRegistry:
    """Return a brand-new SkillRegistry with no permission checker."""
    r = SkillRegistry()
    r._permission_checker = None  # prevent lazy import in unit tests
    return r


async def _echo(**kwargs) -> dict:
    """Simple async handler that returns its inputs."""
    return kwargs


def _sync_echo(**kwargs) -> dict:
    """Simple sync handler that returns its inputs."""
    return kwargs


# ===========================================================================
# A) SkillErrorCode / is_retryable_error
# ===========================================================================


class TestSkillErrorCode:
    def test_retryable_codes(self):
        retryable = [
            SkillErrorCode.EXECUTION_ERROR,
            SkillErrorCode.TIMEOUT,
            SkillErrorCode.DEPENDENCY_UNAVAILABLE,
            SkillErrorCode.RATE_LIMITED,
        ]
        for code in retryable:
            assert is_retryable_error(code), f"{code} should be retryable"

    def test_non_retryable_codes(self):
        non_retryable = [
            SkillErrorCode.NOT_FOUND,
            SkillErrorCode.INVALID_INPUT,
            SkillErrorCode.PERMISSION_DENIED,
            SkillErrorCode.HANDLER_MISSING,
            SkillErrorCode.INTERNAL_ERROR,
        ]
        for code in non_retryable:
            assert not is_retryable_error(code), f"{code} should NOT be retryable"

    def test_all_codes_are_strings(self):
        for code in SkillErrorCode:
            assert isinstance(code.value, str)


# ===========================================================================
# B) SkillRequest validation
# ===========================================================================


class TestSkillRequest:
    def test_defaults_generate_trace_id(self):
        req = SkillRequest(skill_name="foo")
        assert req.trace_id  # auto-generated UUID

    def test_to_dict(self):
        req = SkillRequest(skill_name="bar", inputs={"x": 1})
        d = req.to_dict()
        assert d["skill_name"] == "bar"
        assert d["inputs"] == {"x": 1}

    def test_validate_ok(self):
        req = SkillRequest(skill_name="ok", inputs={})
        validate_skill_request(req)  # must not raise

    def test_validate_empty_name_raises(self):
        req = SkillRequest(skill_name="   ")
        with pytest.raises(ValueError, match="skill_name"):
            validate_skill_request(req)

    def test_validate_non_dict_inputs_raises(self):
        req = SkillRequest(skill_name="foo")
        req.inputs = "not-a-dict"  # type: ignore[assignment]
        with pytest.raises(ValueError, match="inputs"):
            validate_skill_request(req)

    def test_validate_negative_timeout_raises(self):
        req = SkillRequest(skill_name="foo", timeout_s=-1)
        with pytest.raises(ValueError, match="timeout_s"):
            validate_skill_request(req)

    def test_validate_zero_timeout_raises(self):
        req = SkillRequest(skill_name="foo", timeout_s=0)
        with pytest.raises(ValueError, match="timeout_s"):
            validate_skill_request(req)

    def test_validate_empty_trace_id_raises(self):
        req = SkillRequest(skill_name="foo")
        req.trace_id = ""
        with pytest.raises(ValueError, match="trace_id"):
            validate_skill_request(req)


# ===========================================================================
# C) SkillResponse / SkillError
# ===========================================================================


class TestSkillResponse:
    def test_success_factory(self):
        resp = SkillResponse.success("s", "t", outputs=42)
        assert resp.ok
        assert resp.status == SkillStatus.SUCCESS
        assert resp.outputs == 42
        assert resp.errors == []

    def test_failure_factory(self):
        resp = SkillResponse.failure("s", "t", SkillErrorCode.NOT_FOUND, "missing")
        assert not resp.ok
        assert resp.status == SkillStatus.FAILURE
        assert resp.first_error is not None
        assert resp.first_error.code == SkillErrorCode.NOT_FOUND

    def test_to_dict_round_trip(self):
        resp = SkillResponse.success("echo", "tid-1", outputs={"a": 1})
        d = resp.to_dict()
        assert d["skill_name"] == "echo"
        assert d["status"] == "success"
        assert d["outputs"] == {"a": 1}
        assert d["errors"] == []

    def test_validate_success_no_errors_ok(self):
        resp = SkillResponse.success("s", "t", outputs=None)
        validate_skill_response(resp)  # must not raise

    def test_validate_failure_requires_errors(self):
        resp = SkillResponse(skill_name="s", trace_id="t", status=SkillStatus.FAILURE)
        with pytest.raises(ValueError, match="error"):
            validate_skill_response(resp)

    def test_validate_success_with_errors_raises(self):
        resp = SkillResponse.success("s", "t", outputs=None)
        resp.errors = [SkillError(code=SkillErrorCode.INTERNAL_ERROR, message="oops")]
        with pytest.raises(ValueError, match="errors"):
            validate_skill_response(resp)

    def test_skill_error_retryable_flag(self):
        err = SkillError(code=SkillErrorCode.TIMEOUT, message="slow")
        assert err.retryable is True

    def test_skill_error_non_retryable_flag(self):
        err = SkillError(code=SkillErrorCode.NOT_FOUND, message="gone")
        assert err.retryable is False


# ===========================================================================
# D) SkillMetrics timing
# ===========================================================================


class TestSkillMetrics:
    def test_finish_sets_duration(self):
        m = SkillMetrics()
        m.finish()
        assert m.duration_ms >= 0
        assert m.finished_at >= m.started_at

    def test_to_dict_keys(self):
        m = SkillMetrics(executor="mcp:fs")
        m.finish()
        d = m.to_dict()
        assert "duration_ms" in d
        assert d["executor"] == "mcp:fs"


# ===========================================================================
# E) SkillRegistry — registration / discovery
# ===========================================================================


class TestSkillRegistryRegistration:
    def test_register_and_get(self):
        r = _fresh_registry()
        r.register_skill("echo", _echo)
        entry = r.get_skill("echo")
        assert entry is not None
        assert entry.name == "echo"

    def test_has_skill(self):
        r = _fresh_registry()
        assert not r.has_skill("x")
        r.register_skill("x", _echo)
        assert r.has_skill("x")

    def test_skill_count(self):
        r = _fresh_registry()
        assert r.skill_count() == 0
        r.register_skill("a", _echo)
        r.register_skill("b", _echo)
        assert r.skill_count() == 2

    def test_list_skills_returns_dicts(self):
        r = _fresh_registry()
        r.register_skill("s1", _echo, description="first", tags=["a"])
        items = r.list_skills()
        assert len(items) == 1
        assert items[0]["name"] == "s1"
        assert items[0]["tags"] == ["a"]

    def test_overwrite_warns(self, caplog):
        r = _fresh_registry()
        r.register_skill("dup", _echo)
        with caplog.at_level(logging.WARNING, logger="Galaxy.SkillRegistry"):
            r.register_skill("dup", _sync_echo)
        assert "overwriting" in caplog.text.lower()
        assert r.get_skill("dup").handler is _sync_echo

    def test_metadata_stored(self):
        r = _fresh_registry()
        r.register_skill("m", _echo, metadata={"owner": "tests"})
        entry = r.get_skill("m")
        assert entry.metadata["owner"] == "tests"

    def test_permission_tool_name_defaults_to_name(self):
        r = _fresh_registry()
        r.register_skill("foo", _echo)
        assert r.get_skill("foo").permission_tool_name == "foo"

    def test_permission_tool_name_override(self):
        r = _fresh_registry()
        r.register_skill("foo", _echo, permission_tool_name="mcp__*__foo")
        assert r.get_skill("foo").permission_tool_name == "mcp__*__foo"


# ===========================================================================
# F) SkillRegistry — handler invocation (async + sync)
# ===========================================================================


class TestSkillRegistryInvoke:
    async def test_async_handler(self):
        r = _fresh_registry()
        r.register_skill("echo", _echo)
        req = SkillRequest(skill_name="echo", inputs={"val": 99})
        resp = await r.invoke(req)
        assert resp.ok
        assert resp.outputs == {"val": 99}

    async def test_sync_handler(self):
        r = _fresh_registry()
        r.register_skill("sync_echo", _sync_echo)
        req = SkillRequest(skill_name="sync_echo", inputs={"x": "hi"})
        resp = await r.invoke(req)
        assert resp.ok
        assert resp.outputs == {"x": "hi"}

    async def test_metrics_populated(self):
        r = _fresh_registry()
        r.register_skill("echo", _echo)
        req = SkillRequest(skill_name="echo", inputs={})
        resp = await r.invoke(req)
        assert resp.metrics.duration_ms >= 0
        assert resp.metrics.finished_at > 0


# ===========================================================================
# G) SkillRegistry — NOT_FOUND
# ===========================================================================


class TestSkillRegistryNotFound:
    async def test_not_found_returns_failure(self):
        r = _fresh_registry()
        req = SkillRequest(skill_name="does_not_exist")
        resp = await r.invoke(req)
        assert not resp.ok
        assert resp.first_error.code == SkillErrorCode.NOT_FOUND

    async def test_not_found_is_not_retryable(self):
        r = _fresh_registry()
        req = SkillRequest(skill_name="nope")
        resp = await r.invoke(req)
        assert resp.first_error.retryable is False


# ===========================================================================
# H) INVALID_INPUT (contract violation)
# ===========================================================================


class TestSkillRegistryInvalidInput:
    async def test_empty_skill_name_is_invalid(self):
        r = _fresh_registry()
        req = SkillRequest(skill_name="")
        resp = await r.invoke(req)
        assert not resp.ok
        assert resp.first_error.code == SkillErrorCode.INVALID_INPUT

    async def test_bad_inputs_type_is_invalid(self):
        r = _fresh_registry()
        req = SkillRequest(skill_name="foo")
        req.inputs = [1, 2, 3]  # type: ignore[assignment]
        resp = await r.invoke(req)
        assert not resp.ok
        assert resp.first_error.code == SkillErrorCode.INVALID_INPUT


# ===========================================================================
# I) EXECUTION_ERROR — handler raises
# ===========================================================================


class TestSkillRegistryExecutionError:
    async def test_handler_exception_returns_failure(self):
        r = _fresh_registry()

        async def _boom(**_):
            raise RuntimeError("kaboom")

        r.register_skill("boom", _boom)
        req = SkillRequest(skill_name="boom", inputs={})
        resp = await r.invoke(req)
        assert not resp.ok
        assert resp.first_error.code == SkillErrorCode.EXECUTION_ERROR
        assert "kaboom" in resp.first_error.message

    async def test_execution_error_is_retryable(self):
        r = _fresh_registry()

        async def _fail(**_):
            raise ValueError("fail")

        r.register_skill("fail", _fail)
        resp = await r.invoke(SkillRequest(skill_name="fail"))
        assert resp.first_error.retryable is True


# ===========================================================================
# J) TIMEOUT path
# ===========================================================================


class TestSkillRegistryTimeout:
    async def test_timeout_returns_failure(self):
        r = _fresh_registry()

        async def _slow(**_):
            await asyncio.sleep(10)

        r.register_skill("slow", _slow)
        req = SkillRequest(skill_name="slow", timeout_s=0.05)
        resp = await r.invoke(req)
        assert not resp.ok
        assert resp.first_error.code == SkillErrorCode.TIMEOUT

    async def test_timeout_is_retryable(self):
        r = _fresh_registry()

        async def _slow(**_):
            await asyncio.sleep(10)

        r.register_skill("slow2", _slow)
        resp = await r.invoke(SkillRequest(skill_name="slow2", timeout_s=0.05))
        assert resp.first_error.retryable is True


# ===========================================================================
# K) Permission denied
# ===========================================================================


class TestSkillRegistryPermissionDenied:
    async def test_denied_returns_failure(self):
        r = _fresh_registry()

        mock_checker = MagicMock()
        mock_result = MagicMock()
        mock_result.allowed = False
        mock_result.reason = "blocked"
        mock_checker.check.return_value = mock_result
        r._permission_checker = mock_checker

        r.register_skill("op", _echo)
        resp = await r.invoke(SkillRequest(skill_name="op"))
        assert not resp.ok
        assert resp.first_error.code == SkillErrorCode.PERMISSION_DENIED
        assert "blocked" in resp.first_error.message


# ===========================================================================
# L) Permission requires confirmation
# ===========================================================================


class TestSkillRegistryRequiresConfirmation:
    async def test_confirmation_required_returns_failure_with_flag(self):
        r = _fresh_registry()

        mock_checker = MagicMock()
        mock_result = MagicMock()
        mock_result.allowed = True
        mock_result.requires_confirmation = True
        mock_result.risk_level = "dangerous"
        mock_checker.check.return_value = mock_result
        r._permission_checker = mock_checker

        r.register_skill("danger", _echo)
        resp = await r.invoke(SkillRequest(skill_name="danger"))
        assert not resp.ok
        assert resp.first_error.code == SkillErrorCode.PERMISSION_DENIED
        assert resp.first_error.details.get("requires_confirmation") is True


# ===========================================================================
# M) Permission checker raises → allow by default
# ===========================================================================


class TestSkillRegistryPermissionCheckerRaises:
    async def test_checker_exception_allows(self):
        r = _fresh_registry()

        mock_checker = MagicMock()
        mock_checker.check.side_effect = RuntimeError("checker crashed")
        r._permission_checker = mock_checker

        r.register_skill("safe", _echo)
        resp = await r.invoke(SkillRequest(skill_name="safe", inputs={"k": "v"}))
        # Should succeed — checker errors are suppressed
        assert resp.ok
        assert resp.outputs == {"k": "v"}


# ===========================================================================
# N) Observability log entries
# ===========================================================================


class TestSkillRegistryObservability:
    async def test_success_log_emitted(self, caplog):
        r = _fresh_registry()
        r.register_skill("log_echo", _echo)
        with caplog.at_level(logging.INFO, logger="Galaxy.SkillRegistry"):
            await r.invoke(SkillRequest(skill_name="log_echo", inputs={"z": 1}))
        assert "skill_call" in caplog.text
        assert "log_echo" in caplog.text
        assert "success" in caplog.text

    async def test_failure_log_emitted(self, caplog):
        r = _fresh_registry()
        with caplog.at_level(logging.WARNING, logger="Galaxy.SkillRegistry"):
            await r.invoke(SkillRequest(skill_name="missing"))
        assert "skill_call" in caplog.text
        assert "missing" in caplog.text


# ===========================================================================
# O) unregister_skill
# ===========================================================================


class TestSkillRegistryUnregister:
    def test_unregister_existing(self):
        r = _fresh_registry()
        r.register_skill("to_del", _echo)
        assert r.has_skill("to_del")
        result = r.unregister_skill("to_del")
        assert result is True
        assert not r.has_skill("to_del")

    def test_unregister_nonexistent_returns_false(self):
        r = _fresh_registry()
        assert r.unregister_skill("ghost") is False


# ===========================================================================
# P) Singleton helpers
# ===========================================================================


class TestSkillRegistrySingleton:
    def test_get_registry_returns_same_instance(self):
        reset_skill_registry()
        r1 = get_skill_registry()
        r2 = get_skill_registry()
        assert r1 is r2

    def test_reset_creates_new_instance(self):
        reset_skill_registry()
        r1 = get_skill_registry()
        reset_skill_registry()
        r2 = get_skill_registry()
        assert r1 is not r2

    def teardown_method(self, _method):
        reset_skill_registry()


# ===========================================================================
# Q) SkillResponse.to_dict() round-trip
# ===========================================================================


class TestSkillResponseToDict:
    def test_failure_to_dict_includes_errors(self):
        resp = SkillResponse.failure(
            "s", "tid", SkillErrorCode.EXECUTION_ERROR, "boom"
        )
        d = resp.to_dict()
        assert d["status"] == "failure"
        assert len(d["errors"]) == 1
        assert d["errors"][0]["code"] == "execution_error"
        assert d["errors"][0]["retryable"] is True

    def test_metrics_in_to_dict(self):
        m = SkillMetrics(executor="test_exec")
        m.finish()
        resp = SkillResponse.success("s", "t", outputs=None, metrics=m)
        d = resp.to_dict()
        assert d["metrics"]["executor"] == "test_exec"
        assert d["metrics"]["duration_ms"] >= 0


# ===========================================================================
# R) openclawd._dispatch_tool_call skill__ path routes through registry
# ===========================================================================


class TestOpenClawdSkillDispatchRouting:
    """Verify that the skill__ dispatch path in OpenClawd.
    goes through the SkillRegistry and emits observability logs.
    """

    async def test_skill_dispatch_uses_registry(self):
        """_dispatch_tool_call('skill__myfunc', ...) must invoke
        the handler registered in the SkillRegistry (if present)
        and return {success: True, result: ...}.
        """
        from core.skill_registry import get_skill_registry, reset_skill_registry

        reset_skill_registry()
        registry = get_skill_registry()
        registry._permission_checker = None  # disable perm checks in test

        called_with: list = []

        async def _test_handler(**kwargs):
            called_with.append(kwargs)
            return {"computed": True}

        registry.register_skill(
            "skill__myfunc",
            _test_handler,
            source="test",
        )

        # Build a minimal OpenClawd-like object with _dispatch_tool_call
        from core.openclawd import OpenClawd
        oc = OpenClawd.__new__(OpenClawd)
        # Minimal required state
        oc._tool_permission_checker = None

        result = await oc._dispatch_tool_call("skill__myfunc", {"arg": "val"})

        assert result["success"] is True
        assert result["result"] == {"computed": True}
        assert called_with == [{"arg": "val"}]

        reset_skill_registry()

    async def test_skill_dispatch_lazy_registers_adapter(self):
        """When a skill is NOT pre-registered, an adapter is auto-created
        that delegates to skill_loader.execute.
        """
        from core.skill_registry import get_skill_registry, reset_skill_registry

        reset_skill_registry()

        # Mock skill_loader.execute
        mock_execute = AsyncMock(return_value="adapter_result")

        with patch("core.skill_loader.skill_loader") as mock_sl:
            mock_sl.execute = mock_execute

            from core.openclawd import OpenClawd
            oc = OpenClawd.__new__(OpenClawd)
            oc._tool_permission_checker = None

            result = await oc._dispatch_tool_call("skill__lazy_skill", {"p": 1})

        # The adapter should have been registered and called
        assert result["success"] is True
        assert result["result"] == "adapter_result"
        mock_execute.assert_called_once_with("lazy_skill", p=1)

        reset_skill_registry()
