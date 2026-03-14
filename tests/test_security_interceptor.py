"""
tests/test_security_interceptor.py
=====================================

Unit tests for core.control_plane.security_interceptor.

All tests involving asyncio use pytest-asyncio (asyncio_mode = auto
per pytest.ini).  Tests that verify timing use very short timeouts
(< 0.5 s) to keep the suite fast while still validating async behaviour.
"""

import asyncio

import pytest

from core.control_plane.security_interceptor import (
    ApprovalAuditEntry,
    ApprovalDeniedError,
    ApprovalRegistry,
    ApprovalRequest,
    ApprovalStatus,
    ApprovalTimeoutError,
    RiskLevel,
    SecurityInterceptor,
)


# ---------------------------------------------------------------------------
# ApprovalRequest model tests
# ---------------------------------------------------------------------------

class TestApprovalRequest:
    def test_defaults(self):
        req = ApprovalRequest(action="do_something")
        assert req.request_id.startswith("apv_")
        assert len(req.ack_token) > 20
        assert req.status == ApprovalStatus.PENDING
        assert req.risk_level == RiskLevel.MEDIUM

    def test_unique_ids(self):
        r1 = ApprovalRequest(action="a")
        r2 = ApprovalRequest(action="b")
        assert r1.request_id != r2.request_id
        assert r1.ack_token != r2.ack_token

    def test_all_fields(self):
        req = ApprovalRequest(
            action="delete_data",
            task_id="t1",
            risk_level=RiskLevel.CRITICAL,
            requestor="scheduler",
            context={"target": "device_xyz"},
        )
        assert req.task_id == "t1"
        assert req.risk_level == RiskLevel.CRITICAL
        assert req.context["target"] == "device_xyz"


# ---------------------------------------------------------------------------
# ApprovalRegistry tests
# ---------------------------------------------------------------------------

class TestApprovalRegistry:
    def _make_registry_with_request(self, action="test_action"):
        registry = ApprovalRegistry()
        req = ApprovalRequest(action=action)
        registry._register(req)
        return registry, req

    def test_register_makes_pending(self):
        registry, req = self._make_registry_with_request()
        pending = registry.list_pending()
        assert len(pending) == 1
        assert pending[0].request_id == req.request_id

    def test_ack_correct_token_grants(self):
        registry, req = self._make_registry_with_request()
        result = registry.ack(req.request_id, req.ack_token)
        assert result is True
        resolved = registry.get_request(req.request_id)
        assert resolved.status == ApprovalStatus.GRANTED

    def test_ack_wrong_token_rejected(self):
        registry, req = self._make_registry_with_request()
        result = registry.ack(req.request_id, "bad_token")
        assert result is False
        resolved = registry.get_request(req.request_id)
        assert resolved.status == ApprovalStatus.PENDING

    def test_ack_nonexistent_request(self):
        registry = ApprovalRegistry()
        assert registry.ack("nonexistent", "any") is False

    def test_deny_resolves(self):
        registry, req = self._make_registry_with_request()
        result = registry.deny(req.request_id, operator="alice", reason="policy")
        assert result is True
        resolved = registry.get_request(req.request_id)
        assert resolved.status == ApprovalStatus.DENIED
        assert resolved.deny_reason == "policy"
        assert resolved.resolved_by == "alice"

    def test_deny_nonexistent(self):
        registry = ApprovalRegistry()
        assert registry.deny("x") is False

    def test_cannot_ack_after_deny(self):
        registry, req = self._make_registry_with_request()
        registry.deny(req.request_id)
        result = registry.ack(req.request_id, req.ack_token)
        assert result is False

    def test_list_pending_empty_after_resolve(self):
        registry, req = self._make_registry_with_request()
        registry.ack(req.request_id, req.ack_token)
        assert registry.list_pending() == []

    def test_audit_log_populated_on_grant(self):
        registry, req = self._make_registry_with_request()
        registry.ack(req.request_id, req.ack_token)
        log = registry.audit_log()
        assert len(log) == 1
        assert isinstance(log[0], ApprovalAuditEntry)
        assert log[0].status == ApprovalStatus.GRANTED

    def test_audit_log_populated_on_deny(self):
        registry, req = self._make_registry_with_request()
        registry.deny(req.request_id)
        log = registry.audit_log()
        assert len(log) == 1
        assert log[0].status == ApprovalStatus.DENIED

    def test_audit_entry_frozen(self):
        registry, req = self._make_registry_with_request()
        registry.ack(req.request_id, req.ack_token)
        entry = registry.audit_log()[0]
        with pytest.raises(Exception):
            entry.status = ApprovalStatus.PENDING  # type: ignore[misc]

    def test_get_request_returns_none_for_unknown(self):
        registry = ApprovalRegistry()
        assert registry.get_request("unknown") is None

    def test_multiple_requests_independent(self):
        registry = ApprovalRegistry()
        reqs = [ApprovalRequest(action=f"action_{i}") for i in range(3)]
        for r in reqs:
            registry._register(r)
        assert len(registry.list_pending()) == 3
        registry.ack(reqs[0].request_id, reqs[0].ack_token)
        assert len(registry.list_pending()) == 2


# ---------------------------------------------------------------------------
# SecurityInterceptor async tests
# ---------------------------------------------------------------------------

class TestSecurityInterceptor:
    async def test_require_approval_granted(self):
        registry = ApprovalRegistry()
        interceptor = SecurityInterceptor(registry=registry, default_timeout=5.0)

        async def approve_soon():
            await asyncio.sleep(0.05)
            pending = registry.list_pending()
            assert len(pending) == 1
            req = pending[0]
            registry.ack(req.request_id, req.ack_token, operator="operator_1")

        await asyncio.gather(
            interceptor.require_approval(
                "deploy_agent",
                task_id="t1",
                risk_level=RiskLevel.HIGH,
                requestor="scheduler",
            ),
            approve_soon(),
        )

        log = registry.audit_log()
        assert log[0].status == ApprovalStatus.GRANTED
        assert log[0].resolved_by == "operator_1"

    async def test_require_approval_returns_ack_token(self):
        registry = ApprovalRegistry()
        interceptor = SecurityInterceptor(registry=registry, default_timeout=5.0)
        returned_token: list = []

        async def capture():
            token = await interceptor.require_approval("action_x")
            returned_token.append(token)

        async def approve():
            await asyncio.sleep(0.05)
            pending = registry.list_pending()
            req = pending[0]
            registry.ack(req.request_id, req.ack_token)

        await asyncio.gather(capture(), approve())
        assert len(returned_token) == 1
        assert len(returned_token[0]) > 20  # non-empty token

    async def test_require_approval_timeout(self):
        registry = ApprovalRegistry()
        interceptor = SecurityInterceptor(registry=registry)

        with pytest.raises(ApprovalTimeoutError) as exc_info:
            await interceptor.require_approval(
                "dangerous_delete",
                timeout=0.1,
            )

        err = exc_info.value
        assert err.timeout_seconds == 0.1
        # Registry should reflect timed-out state
        log = registry.audit_log()
        assert len(log) == 1
        assert log[0].status == ApprovalStatus.TIMED_OUT

    async def test_require_approval_denied(self):
        registry = ApprovalRegistry()
        interceptor = SecurityInterceptor(registry=registry, default_timeout=5.0)

        async def deny_soon():
            await asyncio.sleep(0.05)
            pending = registry.list_pending()
            req = pending[0]
            registry.deny(req.request_id, operator="alice", reason="not allowed")

        with pytest.raises(ApprovalDeniedError) as exc_info:
            await asyncio.gather(
                interceptor.require_approval("restricted_action"),
                deny_soon(),
            )

        err = exc_info.value
        assert "not allowed" in err.reason

    async def test_require_approval_no_event_loop_blocking(self):
        """
        Verify that require_approval does not block the event loop.
        A concurrent sleeper should progress while the approval is pending.
        """
        registry = ApprovalRegistry()
        interceptor = SecurityInterceptor(registry=registry, default_timeout=2.0)
        progress: list = []

        async def concurrent_work():
            for i in range(3):
                await asyncio.sleep(0.02)
                progress.append(i)

        async def approve():
            await asyncio.sleep(0.1)
            pending = registry.list_pending()
            if pending:
                req = pending[0]
                registry.ack(req.request_id, req.ack_token)

        await asyncio.gather(
            interceptor.require_approval("action"),
            concurrent_work(),
            approve(),
        )
        # concurrent_work should have completed at least some iterations
        assert len(progress) >= 2

    async def test_bypass_auto_approves(self):
        registry = ApprovalRegistry()
        interceptor = SecurityInterceptor(registry=registry)

        token = await interceptor.bypass(
            "telemetry_upload",
            task_id="t_bg",
            risk_level=RiskLevel.LOW,
            requestor="monitor",
        )
        assert token is not None
        log = registry.audit_log()
        assert len(log) == 1
        assert log[0].status == ApprovalStatus.GRANTED
        assert log[0].resolved_by == "system:bypass"

    async def test_multiple_concurrent_approvals(self):
        """Multiple parallel require_approval calls should be independent."""
        registry = ApprovalRegistry()
        interceptor = SecurityInterceptor(registry=registry, default_timeout=5.0)

        async def do_approval(action: str):
            await interceptor.require_approval(action, timeout=2.0)

        async def approve_all():
            await asyncio.sleep(0.1)
            for req in list(registry.list_pending()):
                registry.ack(req.request_id, req.ack_token)

        await asyncio.gather(
            do_approval("action_1"),
            do_approval("action_2"),
            do_approval("action_3"),
            approve_all(),
        )

        log = registry.audit_log()
        granted = [e for e in log if e.status == ApprovalStatus.GRANTED]
        assert len(granted) == 3

    async def test_per_call_timeout_override(self):
        """Verify that per-call timeout takes priority over default."""
        registry = ApprovalRegistry()
        interceptor = SecurityInterceptor(registry=registry, default_timeout=60.0)

        with pytest.raises(ApprovalTimeoutError) as exc_info:
            await interceptor.require_approval("fast_timeout_action", timeout=0.05)

        assert exc_info.value.timeout_seconds == 0.05

    async def test_default_timeout_used_when_not_overridden(self):
        """Verify default_timeout is used when per-call timeout is not set."""
        registry = ApprovalRegistry()
        interceptor = SecurityInterceptor(registry=registry, default_timeout=0.05)

        with pytest.raises(ApprovalTimeoutError) as exc_info:
            await interceptor.require_approval("action_default_to")

        assert exc_info.value.timeout_seconds == 0.05
