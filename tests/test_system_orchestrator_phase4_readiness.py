from __future__ import annotations


def test_phase4_background_subsystems_reports_degraded_when_dispatch_not_ready(monkeypatch):
    from core.system_orchestrator import SystemOrchestrator, PhaseStatus
    import core.runtime.source_dispatch_orchestrator as orchestrator

    class _Plan:
        ready = False
        readiness_notes = ["remote_handoff:no_target_selected"]

    monkeypatch.setattr(orchestrator, "build_source_dispatch_plan", lambda: _Plan())

    result = SystemOrchestrator()._run_phase_4_background_subsystems()

    assert result.status == PhaseStatus.DEGRADED
    assert "dispatch_plan_not_ready" in result.detail
    assert result.data["checks"]["dispatch_plan_ready"] is False
