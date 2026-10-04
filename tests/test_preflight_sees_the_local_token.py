"""启动预检：本机自签令牌已就绪时，不把"没配共享口令"报成阻断；预检异常不再因属性名写错而吞掉。

真机启动日志：``data/api_token.json`` 已经签好，预检却仍先红一行阻断（缺 GALAXY_API_TOKEN）；
Phase 3 里还抛出 ``'PreflightReport' object has no attribute 'critical_findings'``
（属性实际叫 ``criticals``），被泛化的 except 吞成一句"环境有欠缺"。
"""

from __future__ import annotations

import json

import pytest

from core.config_preflight import PreflightReport, run_preflight


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("GALAXY_API_TOKEN", raising=False)
    monkeypatch.delenv("GALAXY_API_TOKENS", raising=False)
    monkeypatch.delenv("GALAXY_REQUIRE_API_TOKEN", raising=False)
    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "true")
    return tmp_path


def _critical_vars():
    report = run_preflight(dry_run=True, fail_fast=False, verbose=False)
    return [f.check.var for f in report.criticals]


def test_local_token_on_disk_clears_the_missing_shared_token_critical(data_dir):
    (data_dir / "api_token.json").write_text(json.dumps({"token": "local-abc"}), encoding="utf-8")
    assert "GALAXY_API_TOKEN" not in _critical_vars()


def test_no_local_token_and_auth_on_is_still_critical(data_dir):
    assert "GALAXY_API_TOKEN" in _critical_vars()


def test_require_flag_still_demands_a_shared_token_even_with_a_local_one(data_dir, monkeypatch):
    (data_dir / "api_token.json").write_text(json.dumps({"token": "local-abc"}), encoding="utf-8")
    monkeypatch.setenv("GALAXY_REQUIRE_API_TOKEN", "true")
    assert "GALAXY_API_TOKEN" in _critical_vars()


def test_preflight_report_has_no_critical_findings_attribute_so_callers_must_use_criticals():
    assert not hasattr(PreflightReport(), "critical_findings")
    assert PreflightReport().criticals == []


def test_phase_3_reports_the_critical_count_instead_of_raising(data_dir):
    from core.system_orchestrator import SystemOrchestrator

    orch = SystemOrchestrator.__new__(SystemOrchestrator)
    orch.strict_preflight = False
    result = orch._run_phase_3_env_checks()
    assert "critical_findings" not in (result.detail or "")
    assert "has no attribute" not in (result.detail or "")
    # 第一次启动：先签令牌再预检，所以没有阻断
    assert (data_dir / "api_token.json").exists()
    assert "CRITICAL" not in (result.detail or "")
