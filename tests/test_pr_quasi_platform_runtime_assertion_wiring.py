from __future__ import annotations

import os

from core.system_orchestrator import OrchestratorReadiness, PhaseStatus, StartupSummary, SystemOrchestrator


def test_phase7_readiness_includes_quasi_platform_boundary_assertion_data() -> None:
    summary = StartupSummary(readiness=OrchestratorReadiness.READY, system_mode="desktop-local")
    result = SystemOrchestrator()._run_phase_7_readiness_summary(summary)

    assert "quasi_platform_state_boundary_status" in result.data
    assert "quasi_platform_state_boundary" in result.data
    assert result.data["quasi_platform_state_boundary_status"] in {"intact", "degraded", "error"}


def test_phase7_strict_mode_fails_when_quasi_platform_assertion_is_not_intact(monkeypatch) -> None:
    import core.bounded_subject_platform_boundary as boundary

    old_strict = os.environ.get("GALAXY_STRICT_AUTHORITY_CHECK")
    try:
        os.environ["GALAXY_STRICT_AUTHORITY_CHECK"] = "1"
        monkeypatch.setattr(
            boundary,
            "build_quasi_platform_runtime_assertion_report",
            lambda: {
                "intact": False,
                "violations": ["forced_violation"],
                "checked_axes": [],
                "final_acceptance_boundary_flags": {},
                "_source": "test",
            },
        )
        summary = StartupSummary(readiness=OrchestratorReadiness.READY, system_mode="desktop-local")
        result = SystemOrchestrator()._run_phase_7_readiness_summary(summary)
        assert result.status == PhaseStatus.FAILED
        assert result.data["quasi_platform_state_boundary_status"] == "degraded"
    finally:
        if old_strict is None:
            os.environ.pop("GALAXY_STRICT_AUTHORITY_CHECK", None)
        else:
            os.environ["GALAXY_STRICT_AUTHORITY_CHECK"] = old_strict


def test_health_quasi_platform_assertion_helper_returns_intact_report_shape() -> None:
    from core.routes.health import _build_quasi_platform_health_assertion

    payload = _build_quasi_platform_health_assertion()
    assert set(payload.keys()) >= {
        "status",
        "intact",
        "violations",
        "checked_axes",
        "final_acceptance_boundary_flags",
        "assertion_source",
    }
    assert payload["status"] in {"intact", "degraded", "error"}
