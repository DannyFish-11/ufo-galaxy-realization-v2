"""
tests/test_clone_to_use_startup_hardening.py
==============================================
Regression tests for clone-to-use startup reliability (health probe order,
preflight token policy, NATS probe strictness).
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestGalaxyUnifiedHealthProbeOrder:
    """HTTP probes must run only after uvicorn binds (inside UnifiedWebUI.start)."""

    def test_galaxy_unified_start_does_not_call_startup_health_check(self):
        from launcher.services import GalaxyUnified

        src = inspect.getsource(GalaxyUnified.start)
        assert "run_startup_health_check" not in src

    def test_unified_web_ui_start_orders_startup_health_main_loop(self):
        from launcher.services import UnifiedWebUI

        src = inspect.getsource(UnifiedWebUI.start)
        # 断言漂移:生产实现已弃用手工 `await server.startup()` +
        # `await server.main_loop()` 两段式(uvicorn ≥0.30 下 startup() 因
        # lifespan 未初始化而崩,见 unified_launcher.py 内注释),改为后台
        # 任务跑公开入口 server.serve(),并轮询公开的 server.started 标志
        # 等到 socket 真正绑定后才做健康探测。本测试守护的契约不变——
        # "HTTP 探测必须发生在 uvicorn 绑定之后"——按新实现的标记重排:
        # serve() 起任务 → 等待 server.started → run_startup_health_check。
        # 用带上下文的标记避免命中实现前的解释性注释文本
        pos_serve = src.find("asyncio.create_task(server.serve())")
        pos_started_wait = src.find("if server.started")
        pos_health = src.find("await run_startup_health_check(")
        assert 0 < pos_serve < pos_started_wait < pos_health
        # 旧的手工两段式不得复活
        assert "await server.startup()" not in src
        assert "await server.main_loop()" not in src


class TestPreflightApiTokenPolicy:
    """GALAXY_API_TOKEN is CRITICAL only when auth or explicit require is on."""

    @pytest.fixture(autouse=True)
    def _clear_token_env(self, monkeypatch):
        monkeypatch.delenv("GALAXY_API_TOKEN", raising=False)

    def test_missing_token_warning_when_auth_off(self, monkeypatch):
        from core.config_preflight import Severity, run_preflight

        monkeypatch.setenv("GALAXY_AUTH_ENABLED", "false")
        monkeypatch.delenv("GALAXY_REQUIRE_API_TOKEN", raising=False)
        report = run_preflight(dry_run=True, fail_fast=False, verbose=False)
        token_rows = [f for f in report.findings if f.check.var == "GALAXY_API_TOKEN"]
        assert token_rows
        assert not token_rows[0].present
        assert token_rows[0].check.severity == Severity.WARNING
        assert report.ok

    def test_missing_token_critical_when_auth_enabled(self, monkeypatch):
        from core.config_preflight import run_preflight

        monkeypatch.setenv("GALAXY_AUTH_ENABLED", "true")
        monkeypatch.delenv("GALAXY_REQUIRE_API_TOKEN", raising=False)
        report = run_preflight(dry_run=True, fail_fast=False, verbose=False)
        crit_vars = [f.check.var for f in report.criticals]
        assert "GALAXY_API_TOKEN" in crit_vars

    def test_missing_token_critical_when_require_flag(self, monkeypatch):
        from core.config_preflight import run_preflight

        monkeypatch.setenv("GALAXY_AUTH_ENABLED", "false")
        monkeypatch.setenv("GALAXY_REQUIRE_API_TOKEN", "true")
        report = run_preflight(dry_run=True, fail_fast=False, verbose=False)
        crit_vars = [f.check.var for f in report.criticals]
        assert "GALAXY_API_TOKEN" in crit_vars

    def test_core_compat_ws_critical_when_enabled_in_protected_cross_device_mode(self, monkeypatch):
        from core.config_preflight import run_preflight

        monkeypatch.setenv("GALAXY_SYSTEM_MODE", "desktop-cross-device")
        monkeypatch.setenv("GALAXY_ENABLE_CORE_COMPAT_WS", "true")
        monkeypatch.delenv("GALAXY_ALLOW_PROTECTED_CORE_COMPAT_WS", raising=False)
        report = run_preflight(dry_run=True, fail_fast=False, mode="gateway", verbose=False)
        crit_vars = [f.check.var for f in report.criticals]
        assert "GALAXY_ENABLE_CORE_COMPAT_WS" in crit_vars

    def test_core_compat_ws_override_clears_protected_cross_device_critical(self, monkeypatch):
        from core.config_preflight import run_preflight

        monkeypatch.setenv("GALAXY_SYSTEM_MODE", "desktop-cross-device")
        monkeypatch.setenv("GALAXY_ENABLE_CORE_COMPAT_WS", "true")
        monkeypatch.setenv("GALAXY_ALLOW_PROTECTED_CORE_COMPAT_WS", "true")
        report = run_preflight(dry_run=True, fail_fast=False, mode="gateway", verbose=False)
        crit_vars = [f.check.var for f in report.criticals]
        assert "GALAXY_ENABLE_CORE_COMPAT_WS" not in crit_vars


class TestNatsProbeStrictness:
    """launcher.health_checks NATS TCP failure severity."""

    def test_nats_non_critical_when_noop_bus(self, monkeypatch):
        from launcher import health_checks

        monkeypatch.delenv("GALAXY_FABRIC_STRICT", raising=False)
        monkeypatch.delenv("GALAXY_CROSS_DEVICE_ENABLED", raising=False)
        monkeypatch.delenv("GALAXY_SYSTEM_MODE", raising=False)
        monkeypatch.delenv("GALAXY_NATS_ENABLED", raising=False)
        assert health_checks._nats_tcp_failure_is_critical() is False

    def test_nats_critical_when_fabric_strict(self, monkeypatch):
        from launcher import health_checks

        monkeypatch.setenv("GALAXY_FABRIC_STRICT", "true")
        monkeypatch.setenv("GALAXY_NATS_ENABLED", "true")
        assert health_checks._nats_tcp_failure_is_critical() is True

    def test_nats_non_critical_when_cross_device_enabled_without_strict(self, monkeypatch):
        from launcher import health_checks

        monkeypatch.delenv("GALAXY_FABRIC_STRICT", raising=False)
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "true")
        assert health_checks._nats_tcp_failure_is_critical() is False

    def test_nats_non_critical_when_nats_enabled_without_strict(self, monkeypatch):
        from launcher import health_checks

        monkeypatch.delenv("GALAXY_FABRIC_STRICT", raising=False)
        monkeypatch.delenv("GALAXY_CROSS_DEVICE_ENABLED", raising=False)
        monkeypatch.setenv("GALAXY_NATS_ENABLED", "true")
        assert health_checks._nats_tcp_failure_is_critical() is False

    def test_nats_critical_uses_posture_policy_when_required(self, monkeypatch):
        from launcher import health_checks

        monkeypatch.setattr(
            "core.nats_posture.evaluate_nats_posture",
            lambda: {"required": True},
        )
        assert health_checks._nats_tcp_failure_is_critical() is True

    def test_nats_non_critical_uses_posture_policy_when_not_required(self, monkeypatch):
        from launcher import health_checks

        monkeypatch.setattr(
            "core.nats_posture.evaluate_nats_posture",
            lambda: {"required": False},
        )
        assert health_checks._nats_tcp_failure_is_critical() is False


class TestNatsPosturePolicy:
    """Canonical NATS posture should stay explicit across env combinations."""

    def test_posture_cross_device_without_strict_is_development_allowed(self, monkeypatch):
        from core.nats_posture import evaluate_nats_posture

        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "true")
        monkeypatch.delenv("GALAXY_FABRIC_STRICT", raising=False)
        monkeypatch.delenv("GALAXY_NATS_ENABLED", raising=False)
        posture = evaluate_nats_posture()
        assert posture["posture"] == "development-allowed-degraded"
        assert posture["required"] is False

    def test_posture_nats_enabled_without_strict_is_development_allowed(self, monkeypatch):
        from core.nats_posture import evaluate_nats_posture

        monkeypatch.setenv("GALAXY_NATS_ENABLED", "true")
        monkeypatch.delenv("GALAXY_FABRIC_STRICT", raising=False)
        posture = evaluate_nats_posture()
        assert posture["posture"] == "development-allowed-degraded"
        assert posture["required"] is False


class TestOrchestratorNatsPostureGuard:
    """Phase-4 preflight should enforce required NATS posture."""

    def test_phase4_fails_when_required_posture_assertion_fails(self, monkeypatch):
        from core.system_orchestrator import PhaseStatus, SystemOrchestrator

        monkeypatch.setattr(
            "core.nats_posture.evaluate_nats_posture",
            lambda: {
                "posture": "production-required",
                "required": True,
                "assertion_ok": False,
                "violation_reason": "required_nats_unreachable",
            },
        )
        result = SystemOrchestrator()._run_phase_4_background_subsystems()
        assert result.status == PhaseStatus.FAILED
        assert "required_nats_unreachable" in result.detail

    def test_phase4_ok_when_development_posture_allows_degraded(self, monkeypatch):
        from core.system_orchestrator import PhaseStatus, SystemOrchestrator

        monkeypatch.setattr(
            "core.nats_posture.evaluate_nats_posture",
            lambda: {
                "posture": "development-allowed-degraded",
                "required": False,
                "assertion_ok": True,
                "violation_reason": "",
            },
        )
        result = SystemOrchestrator()._run_phase_4_background_subsystems()
        assert result.status in {PhaseStatus.OK, PhaseStatus.DEGRADED}
