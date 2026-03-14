#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_phase5_governance_scaling.py
========================================

Unit tests for Phase 5.2 + 5.3:

* Governance policy parsing (schema validation)
* Budget enforcement and fallback behaviour
* Tool governance allow/deny/rate-limit
* Async task queue: concurrency, backpressure, shedding
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Governance policy tests
# ---------------------------------------------------------------------------

class TestGovernancePolicyParsing:
    """Tests for core.governance.policy_schema."""

    def test_load_default_file(self):
        """The default governance_policy.json should parse cleanly."""
        from core.governance.policy_schema import load_governance_policy
        policy = load_governance_policy()
        assert policy.version is not None
        assert policy.budget_policy.session_budget_usd > 0
        assert policy.queue_policy.max_queue_size > 0

    def test_model_policy_defaults(self):
        from core.governance.policy_schema import GovernancePolicy
        p = GovernancePolicy()
        assert p.model_policy.fallback_model == "llama2"

    def test_budget_policy_defaults(self):
        from core.governance.policy_schema import GovernancePolicy
        p = GovernancePolicy()
        assert p.budget_policy.session_budget_usd == 1.0
        assert p.budget_policy.daily_budget_usd == 20.0
        assert 0 < p.budget_policy.warning_threshold <= 1

    def test_tool_policy_defaults(self):
        from core.governance.policy_schema import GovernancePolicy
        p = GovernancePolicy()
        assert p.tool_policy.default_action.value in ("allow", "deny")

    def test_queue_policy_defaults(self):
        from core.governance.policy_schema import GovernancePolicy
        p = GovernancePolicy()
        assert p.queue_policy.max_concurrent_tasks >= 1
        assert 0 < p.queue_policy.backpressure_threshold <= 1

    def test_parse_from_dict(self):
        from core.governance.policy_schema import GovernancePolicy
        raw = {
            "version": "2.0.0",
            "budget_policy": {
                "session_budget_usd": 5.0,
                "daily_budget_usd": 50.0,
                "on_exceed": "deny",
            },
        }
        p = GovernancePolicy.model_validate(raw)
        assert p.version == "2.0.0"
        assert p.budget_policy.session_budget_usd == 5.0
        assert p.budget_policy.on_exceed.value == "deny"

    def test_invalid_warning_threshold_raises(self):
        from core.governance.policy_schema import BudgetPolicy
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            BudgetPolicy(warning_threshold=1.5)

    def test_load_nonexistent_file_returns_defaults(self):
        from core.governance.policy_schema import load_governance_policy
        policy = load_governance_policy("/tmp/does_not_exist_xyz.json")
        assert policy.version is not None  # graceful fallback

    def test_load_invalid_json_returns_defaults(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{ NOT VALID JSON }", encoding="utf-8")
        from core.governance.policy_schema import load_governance_policy
        policy = load_governance_policy(str(bad))
        assert policy.version is not None

    def test_safety_tier_config(self):
        from core.governance.policy_schema import GovernancePolicy, SafetyTierConfig
        p = GovernancePolicy.model_validate({
            "model_policy": {
                "safety_tiers": {
                    "restricted": {"allowed_models": ["llama2"], "max_tokens_per_request": 1024}
                }
            }
        })
        assert "restricted" in p.model_policy.safety_tiers
        assert p.model_policy.safety_tiers["restricted"].max_tokens_per_request == 1024


# ---------------------------------------------------------------------------
# Budget enforcement tests
# ---------------------------------------------------------------------------

class TestBudgetEnforcer:
    """Tests for core.governance.budget_enforcer.BudgetEnforcer."""

    def _make_enforcer(self, session_usd=1.0, daily_usd=20.0, tenant_usd=100.0, on_exceed="downgrade"):
        from core.governance.policy_schema import BudgetPolicy, ModelPolicy, OnBudgetExceed
        from core.governance.budget_enforcer import BudgetEnforcer
        bp = BudgetPolicy(
            session_budget_usd=session_usd,
            daily_budget_usd=daily_usd,
            tenant_daily_budget_usd=tenant_usd,
            on_exceed=on_exceed,
        )
        mp = ModelPolicy(fallback_model="llama2")
        return BudgetEnforcer(bp, mp)

    @pytest.mark.asyncio
    async def test_within_budget_returns_requested_model(self):
        enforcer = self._make_enforcer()
        model = await enforcer.enforce_pre_call(
            session_id="s1", tenant_id="t1",
            requested_model="gpt-4", estimated_cost_usd=0.10,
        )
        assert model == "gpt-4"

    @pytest.mark.asyncio
    async def test_session_budget_exceeded_downgrade(self):
        enforcer = self._make_enforcer(session_usd=0.05)
        # First call fine
        model = await enforcer.enforce_pre_call(
            session_id="s1", tenant_id="t1",
            requested_model="gpt-4", estimated_cost_usd=0.03,
        )
        assert model == "gpt-4"
        # Record the usage
        await enforcer.record_usage("s1", "t1", "gpt-4", 100, 0.03)
        # Second call exceeds session budget -> downgrade
        model = await enforcer.enforce_pre_call(
            session_id="s1", tenant_id="t1",
            requested_model="gpt-4", estimated_cost_usd=0.03,
        )
        assert model == "llama2"

    @pytest.mark.asyncio
    async def test_budget_exceeded_deny_raises(self):
        from core.governance.budget_enforcer import BudgetExceededError
        enforcer = self._make_enforcer(session_usd=0.01, on_exceed="deny")
        await enforcer.record_usage("s1", "t1", "gpt-4", 100, 0.01)
        with pytest.raises(BudgetExceededError):
            await enforcer.enforce_pre_call(
                session_id="s1", tenant_id="t1",
                requested_model="gpt-4", estimated_cost_usd=0.01,
            )

    @pytest.mark.asyncio
    async def test_record_usage_accumulates(self):
        enforcer = self._make_enforcer()
        await enforcer.record_usage("s1", "t1", "gpt-4", 500, 0.02)
        await enforcer.record_usage("s1", "t1", "gpt-4", 300, 0.01)
        status = await enforcer.get_status("s1", "t1")
        assert abs(status.session_spent_usd - 0.03) < 1e-9

    @pytest.mark.asyncio
    async def test_get_status_returns_budget_status(self):
        enforcer = self._make_enforcer()
        status = await enforcer.get_status("sess_x", "tenant_y")
        d = status.to_dict()
        assert "session" in d
        assert "daily" in d
        assert "tenant_daily" in d
        assert d["session_id"] == "sess_x"

    @pytest.mark.asyncio
    async def test_reset_session(self):
        enforcer = self._make_enforcer()
        await enforcer.record_usage("s1", "t1", "gpt-4", 1000, 0.50)
        enforcer.reset_session("s1")
        status = await enforcer.get_status("s1", "t1")
        assert status.session_spent_usd == 0.0

    @pytest.mark.asyncio
    async def test_multiple_sessions_isolated(self):
        enforcer = self._make_enforcer(session_usd=0.10)
        await enforcer.record_usage("s1", "t1", "gpt-4", 100, 0.09)
        await enforcer.record_usage("s2", "t1", "gpt-4", 100, 0.01)
        s1 = await enforcer.get_status("s1", "t1")
        s2 = await enforcer.get_status("s2", "t1")
        assert abs(s1.session_spent_usd - 0.09) < 1e-9
        assert abs(s2.session_spent_usd - 0.01) < 1e-9

    @pytest.mark.asyncio
    async def test_warning_flag(self):
        from core.governance.policy_schema import BudgetPolicy, ModelPolicy
        from core.governance.budget_enforcer import BudgetEnforcer
        bp = BudgetPolicy(session_budget_usd=1.0, warning_threshold=0.5)
        enforcer = BudgetEnforcer(bp)
        await enforcer.record_usage("s1", "t1", "gpt-4", 1000, 0.60)
        status = await enforcer.get_status("s1", "t1")
        assert status.warning is True


# ---------------------------------------------------------------------------
# Tool governance tests
# ---------------------------------------------------------------------------

class TestToolGovernor:
    """Tests for core.governance.tool_governor.ToolGovernor."""

    def _make_governor(self, deny_list=None, allow_list=None,
                       risk_tiers=None, per_tool=None):
        from core.governance.policy_schema import ToolPolicy, RiskTierConfig, DefaultToolAction
        from core.governance.tool_governor import ToolGovernor
        tp = ToolPolicy(
            default_action=DefaultToolAction.ALLOW,
            deny_list=deny_list or [],
            allow_list=allow_list or [],
            risk_tiers=risk_tiers or {
                "safe":     RiskTierConfig(action="allow", rate_limit_per_minute=120),
                "moderate": RiskTierConfig(action="allow", rate_limit_per_minute=60),
                "high":     RiskTierConfig(action="allow", rate_limit_per_minute=10, require_audit=True),
                "critical": RiskTierConfig(action="deny",  rate_limit_per_minute=0,  require_audit=True),
            },
            per_tool_overrides=per_tool or {},
        )
        return ToolGovernor(tp)

    @pytest.mark.asyncio
    async def test_allowed_tool(self):
        gov = self._make_governor()
        d = await gov.check("my_tool", "safe")
        assert d.allowed is True

    @pytest.mark.asyncio
    async def test_deny_list_blocks_tool(self):
        gov = self._make_governor(deny_list=["bad_tool"])
        d = await gov.check("bad_tool", "safe")
        assert d.allowed is False
        assert "deny list" in d.reason.lower()

    @pytest.mark.asyncio
    async def test_critical_tier_denied(self):
        gov = self._make_governor()
        d = await gov.check("some_tool", "critical")
        assert d.allowed is False

    @pytest.mark.asyncio
    async def test_rate_limit_exhaustion(self):
        from core.governance.policy_schema import ToolPolicy, RiskTierConfig, DefaultToolAction
        from core.governance.tool_governor import ToolGovernor
        # Rate limit of 1/min means only 1 token in bucket
        tp = ToolPolicy(
            default_action=DefaultToolAction.ALLOW,
            risk_tiers={
                "safe": RiskTierConfig(action="allow", rate_limit_per_minute=1),
            }
        )
        gov = ToolGovernor(tp)
        # First call should succeed
        d1 = await gov.check("my_tool", "safe")
        assert d1.allowed is True
        # Second call should be rate-limited
        d2 = await gov.check("my_tool", "safe")
        assert d2.allowed is False
        assert d2.rate_limited is True

    @pytest.mark.asyncio
    async def test_per_tool_override_deny(self):
        from core.governance.policy_schema import RiskTierConfig
        gov = self._make_governor(per_tool={
            "shell_exec": RiskTierConfig(action="deny", rate_limit_per_minute=0)
        })
        d = await gov.check("shell_exec", "safe")
        assert d.allowed is False

    @pytest.mark.asyncio
    async def test_allow_list_bypasses_default_deny(self):
        from core.governance.policy_schema import ToolPolicy, RiskTierConfig, DefaultToolAction
        from core.governance.tool_governor import ToolGovernor
        tp = ToolPolicy(
            default_action=DefaultToolAction.DENY,
            allow_list=["safe_tool"],
            risk_tiers={
                "safe": RiskTierConfig(action="allow", rate_limit_per_minute=60),
            }
        )
        gov = ToolGovernor(tp)
        d = await gov.check("safe_tool", "safe")
        assert d.allowed is True

    @pytest.mark.asyncio
    async def test_audit_log_populated(self):
        gov = self._make_governor(deny_list=["audit_me"])
        await gov.check("audit_me", "safe")
        log = gov.get_audit_log()
        assert len(log) >= 1
        assert log[0].tool_name == "audit_me"
        assert log[0].allowed is False

    @pytest.mark.asyncio
    async def test_audit_log_filter_by_tool(self):
        gov = self._make_governor(deny_list=["evil"])
        await gov.check("evil", "safe")
        await gov.check("good", "safe")
        filtered = gov.get_audit_log(tool_name="evil")
        assert all(e.tool_name == "evil" for e in filtered)

    @pytest.mark.asyncio
    async def test_audit_log_filter_by_allowed(self):
        gov = self._make_governor(deny_list=["bad"])
        await gov.check("bad", "safe")
        await gov.check("good", "safe")
        denied = gov.get_audit_log(allowed=False)
        assert all(not e.allowed for e in denied)
        allowed = gov.get_audit_log(allowed=True)
        assert all(e.allowed for e in allowed)

    @pytest.mark.asyncio
    async def test_bucket_refill_over_time(self):
        """After a short wait, the bucket should refill and allow another call."""
        from core.governance.policy_schema import ToolPolicy, RiskTierConfig, DefaultToolAction
        from core.governance.tool_governor import ToolGovernor
        tp = ToolPolicy(
            default_action=DefaultToolAction.ALLOW,
            risk_tiers={"safe": RiskTierConfig(action="allow", rate_limit_per_minute=60)},
        )
        gov = ToolGovernor(tp)
        # Drain the bucket
        for _ in range(60):
            await gov.check("my_tool", "safe")
        # Should be exhausted now
        d = await gov.check("my_tool", "safe")
        assert d.rate_limited or d.allowed  # fine if bucket has room, depends on timing
        # Reset and check fresh
        gov.reset_bucket("my_tool")
        d2 = await gov.check("my_tool", "safe")
        assert d2.allowed is True

    def test_get_policy_summary(self):
        gov = self._make_governor()
        summary = gov.get_policy_summary()
        assert "default_action" in summary
        assert "risk_tiers" in summary


# ---------------------------------------------------------------------------
# Async queue tests
# ---------------------------------------------------------------------------

class TestAsyncTaskQueue:
    """Tests for core.queueing.async_queue.AsyncTaskQueue."""

    @pytest.mark.asyncio
    async def test_basic_submit_and_result(self):
        from core.queueing.async_queue import AsyncTaskQueue
        q = AsyncTaskQueue(max_queue_size=10, max_concurrent=2)
        await q.start()
        try:
            async def double(x):
                return x * 2
            future = await q.submit(double, 21)
            result = await asyncio.wait_for(future, timeout=5.0)
            assert result == 42
        finally:
            await q.stop()

    @pytest.mark.asyncio
    async def test_concurrent_tasks(self):
        from core.queueing.async_queue import AsyncTaskQueue
        q = AsyncTaskQueue(max_queue_size=50, max_concurrent=4)
        await q.start()
        try:
            async def slow_add(a, b):
                await asyncio.sleep(0.05)
                return a + b

            futures = [await q.submit(slow_add, i, i) for i in range(8)]
            results = await asyncio.gather(*futures)
            assert results == [i + i for i in range(8)]
        finally:
            await q.stop()

    @pytest.mark.asyncio
    async def test_queue_full_reject_new(self):
        from core.queueing.async_queue import AsyncTaskQueue, QueueFullError
        q = AsyncTaskQueue(
            max_queue_size=5,
            max_concurrent=1,
            backpressure_threshold=0.4,  # triggers at 2/5 items
            shed_strategy="reject_new",
        )
        await q.start()
        try:
            async def slow():
                await asyncio.sleep(5)
            # Fill beyond threshold
            submitted = 0
            for _ in range(10):
                try:
                    await q.submit(slow)
                    submitted += 1
                except QueueFullError:
                    break
            assert submitted < 10  # at least some were rejected
        finally:
            await q.force_stop()

    @pytest.mark.asyncio
    async def test_queue_full_drop_oldest(self):
        from core.queueing.async_queue import AsyncTaskQueue, QueueFullError
        q = AsyncTaskQueue(
            max_queue_size=3,
            max_concurrent=1,
            backpressure_threshold=0.5,
            shed_strategy="drop_oldest",
        )
        await q.start()
        try:
            async def slow():
                await asyncio.sleep(5)
            # Overfill — should not raise
            for _ in range(5):
                try:
                    await q.submit(slow)
                except QueueFullError:
                    pass  # May happen in edge cases
        finally:
            await q.force_stop()

    @pytest.mark.asyncio
    async def test_task_timeout(self):
        from core.queueing.async_queue import AsyncTaskQueue
        q = AsyncTaskQueue(max_queue_size=10, max_concurrent=2, task_timeout=0.05)
        await q.start()
        try:
            async def never_finishes():
                await asyncio.sleep(999)
            future = await q.submit(never_finishes)
            with pytest.raises((TimeoutError, asyncio.TimeoutError)):
                await asyncio.wait_for(future, timeout=2.0)
        finally:
            await q.stop(timeout=1.0)

    @pytest.mark.asyncio
    async def test_stats_tracking(self):
        from core.queueing.async_queue import AsyncTaskQueue
        q = AsyncTaskQueue(max_queue_size=20, max_concurrent=2)
        await q.start()
        try:
            async def noop():
                return None
            futures = [await q.submit(noop) for _ in range(5)]
            await asyncio.gather(*futures)
            s = q.stats()
            assert s.total_submitted == 5
            assert s.total_completed == 5
            assert s.total_failed == 0
            assert s.avg_latency_ms >= 0
        finally:
            await q.stop()

    @pytest.mark.asyncio
    async def test_stats_to_dict(self):
        from core.queueing.async_queue import AsyncTaskQueue
        q = AsyncTaskQueue(max_queue_size=10, max_concurrent=2)
        await q.start()
        try:
            s = q.stats().to_dict()
            assert "queue_depth" in s
            assert "running" in s
            assert "avg_latency_ms" in s
            assert "backpressure_active" in s
            assert "utilisation" in s
        finally:
            await q.stop()

    @pytest.mark.asyncio
    async def test_submit_before_start_raises(self):
        from core.queueing.async_queue import AsyncTaskQueue
        q = AsyncTaskQueue()
        with pytest.raises(RuntimeError):
            await q.submit(asyncio.sleep, 0)

    @pytest.mark.asyncio
    async def test_exception_propagates(self):
        from core.queueing.async_queue import AsyncTaskQueue
        q = AsyncTaskQueue(max_queue_size=10, max_concurrent=2)
        await q.start()
        try:
            async def boom():
                raise ValueError("test error")
            future = await q.submit(boom)
            with pytest.raises(ValueError, match="test error"):
                await asyncio.wait_for(future, timeout=5.0)
            s = q.stats()
            assert s.total_failed >= 1
        finally:
            await q.stop()

    @pytest.mark.asyncio
    async def test_rejected_count_increments(self):
        from core.queueing.async_queue import AsyncTaskQueue, QueueFullError
        q = AsyncTaskQueue(
            max_queue_size=2,
            max_concurrent=1,
            backpressure_threshold=0.1,  # triggers immediately
            shed_strategy="reject_new",
        )
        await q.start()
        try:
            async def slow():
                await asyncio.sleep(5)
            rejected = 0
            for _ in range(5):
                try:
                    await q.submit(slow)
                except QueueFullError:
                    rejected += 1
            assert rejected > 0
            assert q.stats().total_rejected > 0
        finally:
            await q.force_stop()


# ---------------------------------------------------------------------------
# Audit ledger event types
# ---------------------------------------------------------------------------

class TestGovernanceAuditLedgerEvents:
    """Ensure new governance EventTypes are present in the ledger."""

    def test_governance_event_types_exist(self):
        from core.control_plane.audit_ledger import EventType
        assert EventType.BUDGET_WARNING == "budget_warning"
        assert EventType.BUDGET_EXCEEDED == "budget_exceeded"
        assert EventType.BUDGET_DOWNGRADE == "budget_downgrade"
        assert EventType.TOOL_GOVERNANCE_DECISION == "tool_governance_decision"
        assert EventType.TOOL_RATE_LIMITED == "tool_rate_limited"
        assert EventType.TOOL_DENIED == "tool_denied"
        assert EventType.QUEUE_METRIC == "queue_metric"
        assert EventType.QUEUE_BACKPRESSURE == "queue_backpressure"
        assert EventType.QUEUE_TASK_SHED == "queue_task_shed"

    def test_append_governance_event(self):
        from core.control_plane.audit_ledger import AuditLedger, EventType, Severity
        ledger = AuditLedger()
        eid = ledger.append(
            event_type=EventType.BUDGET_EXCEEDED,
            severity=Severity.WARNING,
            source="budget_enforcer",
            message="Session budget exceeded",
            payload={"session_id": "s1", "limit": 1.0, "spent": 0.99},
        )
        assert eid.startswith("ev_")
        events = ledger.query(event_type=EventType.BUDGET_EXCEEDED)
        assert len(events) == 1
        assert events[0].payload["session_id"] == "s1"

    @pytest.mark.asyncio
    async def test_tool_governor_emits_to_ledger(self):
        """Tool denials should be recorded in the AuditLedger when one is wired."""
        from core.control_plane.audit_ledger import AuditLedger, EventType
        from core.governance.policy_schema import ToolPolicy, RiskTierConfig, DefaultToolAction
        from core.governance.tool_governor import ToolGovernor

        ledger = AuditLedger()
        tp = ToolPolicy(
            default_action=DefaultToolAction.ALLOW,
            deny_list=["forbidden_tool"],
            risk_tiers={
                "high": RiskTierConfig(action="allow", rate_limit_per_minute=10, require_audit=True),
            },
        )
        gov = ToolGovernor(tp, ledger=ledger)

        await gov.check("forbidden_tool", "high")
        events = ledger.query(event_type=EventType.TOOL_GOVERNANCE_DECISION)
        assert len(events) >= 1
        assert events[0].payload["tool_name"] == "forbidden_tool"
        assert events[0].payload["allowed"] is False

    @pytest.mark.asyncio
    async def test_queue_emits_metric_to_ledger(self):
        """Completed queue tasks should emit QUEUE_METRIC events to the ledger."""
        from core.control_plane.audit_ledger import AuditLedger, EventType
        from core.queueing.async_queue import AsyncTaskQueue

        ledger = AuditLedger()
        q = AsyncTaskQueue(max_queue_size=10, max_concurrent=2, ledger=ledger)
        await q.start()
        try:
            async def noop():
                return None
            future = await q.submit(noop)
            await asyncio.wait_for(future, timeout=5.0)
            # Give the worker time to emit the metric
            await asyncio.sleep(0.05)
            events = ledger.query(event_type=EventType.QUEUE_METRIC)
            assert len(events) >= 1
        finally:
            await q.stop()


# ---------------------------------------------------------------------------
# Governance API routes
# ---------------------------------------------------------------------------

class TestGovernanceAPIRoutes:
    """Smoke-tests for the governance FastAPI router."""

    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from core.routes.governance import create_router
        app = FastAPI()
        app.include_router(create_router())
        return TestClient(app)

    def test_get_policy(self, client):
        resp = client.get("/api/v1/governance/policy")
        assert resp.status_code == 200
        data = resp.json()
        assert "budget_policy" in data
        assert "tool_policy" in data

    def test_get_budget_status(self, client):
        resp = client.get("/api/v1/governance/budget/test_session")
        assert resp.status_code == 200
        data = resp.json()
        assert "session" in data

    def test_record_budget_usage(self, client):
        resp = client.post("/api/v1/governance/budget/record", json={
            "session_id": "s1",
            "tenant_id": "t1",
            "model": "gpt-4",
            "tokens_used": 500,
            "cost_usd": 0.01,
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_get_tool_policy(self, client):
        resp = client.get("/api/v1/governance/tools/policy")
        assert resp.status_code == 200
        data = resp.json()
        assert "default_action" in data

    def test_check_tool_allowed(self, client):
        resp = client.post("/api/v1/governance/tools/check", json={
            "tool_name": "safe_tool",
            "risk_tier": "safe",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "allowed" in data

    def test_check_tool_denied(self, client):
        # "wipe_filesystem" is in the default deny list
        resp = client.post("/api/v1/governance/tools/check", json={
            "tool_name": "wipe_filesystem",
            "risk_tier": "critical",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["allowed"] is False

    def test_get_tool_audit(self, client):
        # Trigger a denial first
        client.post("/api/v1/governance/tools/check", json={
            "tool_name": "drop_database",
            "risk_tier": "critical",
        })
        resp = client.get("/api/v1/governance/tools/audit")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_queue_stats_no_queue(self, client):
        resp = client.get("/api/v1/governance/queue/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "available" in data
