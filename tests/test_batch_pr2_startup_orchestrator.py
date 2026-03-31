"""
tests/test_batch_pr2_startup_orchestrator.py
============================================

PR-2: Canonical System Orchestrator — test suite

Validates that:
1. ``core.system_orchestrator`` exports the expected symbols.
2. ``StartupPhase`` has exactly 7 phases in the correct order.
3. ``PhaseResult`` and ``StartupSummary`` have correct semantics.
4. ``SystemOrchestrator.run_startup_sequence()`` runs all 7 phases.
5. ``main.py`` declares ``SYSTEM_ORCHESTRATOR_AUTHORITY`` and references
   ``unified_launcher`` as a subordinate component.
6. ``unified_launcher.py`` docstring acknowledges its subordinate role.
7. Phase hooks are extensible (register_hook API).
8. ``StartupSummary`` correctly aggregates readiness from phase results.
9. ``OrchestratorReadiness`` has the expected values.
10. ``run_startup_sequence`` skips later phases after a FAILED phase.
"""

from __future__ import annotations

import importlib
import pathlib
from unittest.mock import patch, MagicMock

import pytest

PROJECT_ROOT = pathlib.Path(__file__).parent.parent


# ===========================================================================
# 1. Module-level exports
# ===========================================================================

class TestSystemOrchestratorExports:
    def test_module_importable(self):
        mod = importlib.import_module("core.system_orchestrator")
        assert mod is not None

    def test_authority_sentinel_exported(self):
        from core.system_orchestrator import SYSTEM_ORCHESTRATOR_AUTHORITY
        assert isinstance(SYSTEM_ORCHESTRATOR_AUTHORITY, str)
        assert len(SYSTEM_ORCHESTRATOR_AUTHORITY) > 0

    def test_startup_phase_exported(self):
        from core.system_orchestrator import StartupPhase
        assert StartupPhase is not None

    def test_phase_status_exported(self):
        from core.system_orchestrator import PhaseStatus
        assert PhaseStatus is not None

    def test_phase_result_exported(self):
        from core.system_orchestrator import PhaseResult
        assert PhaseResult is not None

    def test_orchestrator_readiness_exported(self):
        from core.system_orchestrator import OrchestratorReadiness
        assert OrchestratorReadiness is not None

    def test_startup_summary_exported(self):
        from core.system_orchestrator import StartupSummary
        assert StartupSummary is not None

    def test_system_orchestrator_class_exported(self):
        from core.system_orchestrator import SystemOrchestrator
        assert SystemOrchestrator is not None


# ===========================================================================
# 2. StartupPhase — 7 phases in order
# ===========================================================================

class TestStartupPhase:
    def test_seven_phases(self):
        from core.system_orchestrator import StartupPhase
        assert len(StartupPhase) == 7

    def test_phase_values_ordered(self):
        from core.system_orchestrator import StartupPhase
        phases = list(StartupPhase)
        for i, phase in enumerate(phases):
            assert phase.value == i + 1, (
                f"Phase {phase.name} should have value {i + 1}, got {phase.value}"
            )

    def test_phase_names(self):
        from core.system_orchestrator import StartupPhase
        expected_names = {
            "LOAD_CONFIG",
            "RESOLVE_MODE",
            "ENV_CHECKS",
            "BACKGROUND_SUBSYSTEMS",
            "RUNTIME_SUBJECT",
            "DESKTOP_SURFACE",
            "READINESS_SUMMARY",
        }
        assert {p.name for p in StartupPhase} == expected_names

    def test_load_config_is_first(self):
        from core.system_orchestrator import StartupPhase
        assert StartupPhase.LOAD_CONFIG.value == 1

    def test_readiness_summary_is_last(self):
        from core.system_orchestrator import StartupPhase
        assert StartupPhase.READINESS_SUMMARY.value == 7


# ===========================================================================
# 3. PhaseResult semantics
# ===========================================================================

class TestPhaseResult:
    def test_ok_status_means_ok_property_true(self):
        from core.system_orchestrator import PhaseResult, PhaseStatus, StartupPhase
        r = PhaseResult(phase=StartupPhase.LOAD_CONFIG, status=PhaseStatus.OK)
        assert r.ok is True

    def test_degraded_status_means_ok_property_true(self):
        from core.system_orchestrator import PhaseResult, PhaseStatus, StartupPhase
        r = PhaseResult(phase=StartupPhase.LOAD_CONFIG, status=PhaseStatus.DEGRADED)
        assert r.ok is True

    def test_skipped_status_means_ok_property_true(self):
        from core.system_orchestrator import PhaseResult, PhaseStatus, StartupPhase
        r = PhaseResult(phase=StartupPhase.LOAD_CONFIG, status=PhaseStatus.SKIPPED)
        assert r.ok is True

    def test_failed_status_means_ok_property_false(self):
        from core.system_orchestrator import PhaseResult, PhaseStatus, StartupPhase
        r = PhaseResult(phase=StartupPhase.LOAD_CONFIG, status=PhaseStatus.FAILED)
        assert r.ok is False

    def test_pending_status_means_ok_property_false(self):
        from core.system_orchestrator import PhaseResult, PhaseStatus, StartupPhase
        r = PhaseResult(phase=StartupPhase.LOAD_CONFIG, status=PhaseStatus.PENDING)
        assert r.ok is False

    def test_str_representation_includes_phase_and_status(self):
        from core.system_orchestrator import PhaseResult, PhaseStatus, StartupPhase
        r = PhaseResult(
            phase=StartupPhase.ENV_CHECKS,
            status=PhaseStatus.OK,
            detail="checks passed",
        )
        s = str(r)
        assert "ENV_CHECKS" in s
        assert "OK" in s

    def test_detail_in_str_when_provided(self):
        from core.system_orchestrator import PhaseResult, PhaseStatus, StartupPhase
        r = PhaseResult(
            phase=StartupPhase.LOAD_CONFIG,
            status=PhaseStatus.DEGRADED,
            detail="config not found",
        )
        assert "config not found" in str(r)

    def test_data_field_defaults_to_empty_dict(self):
        from core.system_orchestrator import PhaseResult, PhaseStatus, StartupPhase
        r = PhaseResult(phase=StartupPhase.LOAD_CONFIG, status=PhaseStatus.OK)
        assert r.data == {}

    def test_data_field_preservable(self):
        from core.system_orchestrator import PhaseResult, PhaseStatus, StartupPhase
        r = PhaseResult(
            phase=StartupPhase.RESOLVE_MODE,
            status=PhaseStatus.OK,
            data={"system_mode": "desktop-local"},
        )
        assert r.data["system_mode"] == "desktop-local"


# ===========================================================================
# 4. OrchestratorReadiness
# ===========================================================================

class TestOrchestratorReadiness:
    def test_three_states(self):
        from core.system_orchestrator import OrchestratorReadiness
        assert len(OrchestratorReadiness) == 3

    def test_ready_value(self):
        from core.system_orchestrator import OrchestratorReadiness
        assert OrchestratorReadiness.READY.value == "READY"

    def test_degraded_value(self):
        from core.system_orchestrator import OrchestratorReadiness
        assert OrchestratorReadiness.DEGRADED.value == "DEGRADED"

    def test_failed_value(self):
        from core.system_orchestrator import OrchestratorReadiness
        assert OrchestratorReadiness.FAILED.value == "FAILED"


# ===========================================================================
# 5. StartupSummary aggregation
# ===========================================================================

class TestStartupSummary:
    def test_starts_as_ready(self):
        from core.system_orchestrator import StartupSummary, OrchestratorReadiness
        s = StartupSummary()
        assert s.readiness == OrchestratorReadiness.READY

    def test_add_ok_result_keeps_ready(self):
        from core.system_orchestrator import (
            StartupSummary, OrchestratorReadiness, PhaseResult, PhaseStatus, StartupPhase,
        )
        s = StartupSummary()
        s.add_result(PhaseResult(phase=StartupPhase.LOAD_CONFIG, status=PhaseStatus.OK))
        assert s.readiness == OrchestratorReadiness.READY

    def test_add_degraded_result_sets_degraded(self):
        from core.system_orchestrator import (
            StartupSummary, OrchestratorReadiness, PhaseResult, PhaseStatus, StartupPhase,
        )
        s = StartupSummary()
        s.add_result(PhaseResult(phase=StartupPhase.LOAD_CONFIG, status=PhaseStatus.DEGRADED))
        assert s.readiness == OrchestratorReadiness.DEGRADED

    def test_add_failed_result_sets_failed(self):
        from core.system_orchestrator import (
            StartupSummary, OrchestratorReadiness, PhaseResult, PhaseStatus, StartupPhase,
        )
        s = StartupSummary()
        s.add_result(PhaseResult(phase=StartupPhase.LOAD_CONFIG, status=PhaseStatus.FAILED))
        assert s.readiness == OrchestratorReadiness.FAILED

    def test_failed_is_not_ready(self):
        from core.system_orchestrator import StartupSummary, PhaseResult, PhaseStatus, StartupPhase
        s = StartupSummary()
        s.add_result(PhaseResult(phase=StartupPhase.LOAD_CONFIG, status=PhaseStatus.FAILED))
        assert s.is_ready() is False

    def test_ready_is_ready(self):
        from core.system_orchestrator import StartupSummary, PhaseResult, PhaseStatus, StartupPhase
        s = StartupSummary()
        s.add_result(PhaseResult(phase=StartupPhase.LOAD_CONFIG, status=PhaseStatus.OK))
        assert s.is_ready() is True

    def test_degraded_is_ready(self):
        from core.system_orchestrator import StartupSummary, PhaseResult, PhaseStatus, StartupPhase
        s = StartupSummary()
        s.add_result(PhaseResult(phase=StartupPhase.LOAD_CONFIG, status=PhaseStatus.DEGRADED))
        assert s.is_ready() is True

    def test_str_includes_readiness(self):
        from core.system_orchestrator import StartupSummary
        s = StartupSummary()
        assert "READY" in str(s)

    def test_str_includes_system_mode(self):
        from core.system_orchestrator import StartupSummary
        s = StartupSummary(system_mode="desktop-cross-device")
        assert "desktop-cross-device" in str(s)

    def test_phase_results_accumulate(self):
        from core.system_orchestrator import StartupSummary, PhaseResult, PhaseStatus, StartupPhase
        s = StartupSummary()
        s.add_result(PhaseResult(phase=StartupPhase.LOAD_CONFIG, status=PhaseStatus.OK))
        s.add_result(PhaseResult(phase=StartupPhase.RESOLVE_MODE, status=PhaseStatus.OK))
        assert len(s.phase_results) == 2

    def test_failed_overrides_degraded(self):
        from core.system_orchestrator import (
            StartupSummary, OrchestratorReadiness, PhaseResult, PhaseStatus, StartupPhase,
        )
        s = StartupSummary()
        s.add_result(PhaseResult(phase=StartupPhase.LOAD_CONFIG, status=PhaseStatus.DEGRADED))
        s.add_result(PhaseResult(phase=StartupPhase.RESOLVE_MODE, status=PhaseStatus.FAILED))
        assert s.readiness == OrchestratorReadiness.FAILED

    def test_default_system_mode_is_local(self):
        from core.system_orchestrator import StartupSummary
        s = StartupSummary()
        assert s.system_mode == "desktop-local"


# ===========================================================================
# 6. SystemOrchestrator — run_startup_sequence
# ===========================================================================

class TestSystemOrchestrator:
    def test_instantiable(self):
        from core.system_orchestrator import SystemOrchestrator
        orch = SystemOrchestrator()
        assert orch is not None

    def test_run_startup_sequence_returns_summary(self):
        from core.system_orchestrator import SystemOrchestrator, StartupSummary
        orch = SystemOrchestrator()
        summary = orch.run_startup_sequence()
        assert isinstance(summary, StartupSummary)

    def test_run_startup_sequence_has_7_results(self):
        from core.system_orchestrator import SystemOrchestrator, StartupPhase
        orch = SystemOrchestrator()
        summary = orch.run_startup_sequence()
        # All 7 phases must appear in the results
        phases_seen = {r.phase for r in summary.phase_results}
        assert StartupPhase.READINESS_SUMMARY in phases_seen
        assert len(summary.phase_results) == 7

    def test_run_startup_sequence_includes_all_phases(self):
        from core.system_orchestrator import SystemOrchestrator, StartupPhase
        orch = SystemOrchestrator()
        summary = orch.run_startup_sequence()
        phases_seen = {r.phase for r in summary.phase_results}
        for phase in StartupPhase:
            assert phase in phases_seen, f"Phase {phase.name} missing from results"

    def test_phases_appear_in_order(self):
        from core.system_orchestrator import SystemOrchestrator, StartupPhase
        orch = SystemOrchestrator()
        summary = orch.run_startup_sequence()
        # Phase values should be non-decreasing
        values = [r.phase.value for r in summary.phase_results]
        assert values == sorted(values), "Phases must appear in ascending order"

    def test_summary_is_ready_by_default(self):
        from core.system_orchestrator import SystemOrchestrator
        orch = SystemOrchestrator()
        summary = orch.run_startup_sequence()
        assert summary.is_ready()

    def test_system_mode_extracted_from_phase2(self, monkeypatch):
        monkeypatch.delenv("GALAXY_NATS_URL", raising=False)
        monkeypatch.delenv("GALAXY_CROSS_DEVICE_ENABLED", raising=False)
        monkeypatch.setenv("GALAXY_SYSTEM_MODE", "desktop-local")
        from core.system_orchestrator import SystemOrchestrator
        orch = SystemOrchestrator()
        summary = orch.run_startup_sequence()
        assert summary.system_mode in ("desktop-local", "desktop-cross-device")

    def test_continue_on_failure_false_skips_later_phases(self):
        from core.system_orchestrator import (
            SystemOrchestrator, StartupPhase, PhaseResult, PhaseStatus,
        )
        # Force Phase 1 to fail
        orch = SystemOrchestrator(continue_on_failure=False)

        def failing_hook() -> PhaseResult:
            return PhaseResult(
                phase=StartupPhase.LOAD_CONFIG,
                status=PhaseStatus.FAILED,
                detail="injected failure",
            )

        orch.register_hook(StartupPhase.LOAD_CONFIG, failing_hook)
        summary = orch.run_startup_sequence()

        # At least one phase should be SKIPPED
        skipped = [r for r in summary.phase_results if r.status == PhaseStatus.SKIPPED]
        assert len(skipped) > 0

    def test_continue_on_failure_true_does_not_skip(self):
        from core.system_orchestrator import (
            SystemOrchestrator, StartupPhase, PhaseResult, PhaseStatus,
        )
        orch = SystemOrchestrator(continue_on_failure=True)

        def failing_hook() -> PhaseResult:
            return PhaseResult(
                phase=StartupPhase.LOAD_CONFIG,
                status=PhaseStatus.FAILED,
                detail="injected failure",
            )

        orch.register_hook(StartupPhase.LOAD_CONFIG, failing_hook)
        summary = orch.run_startup_sequence()
        skipped = [r for r in summary.phase_results if r.status == PhaseStatus.SKIPPED]
        assert len(skipped) == 0


# ===========================================================================
# 7. Hook registration
# ===========================================================================

class TestHookRegistration:
    def test_register_hook_called_during_phase(self):
        from core.system_orchestrator import (
            SystemOrchestrator, StartupPhase, PhaseResult, PhaseStatus,
        )
        calls = []

        def my_hook() -> PhaseResult:
            calls.append("called")
            return PhaseResult(phase=StartupPhase.ENV_CHECKS, status=PhaseStatus.OK)

        orch = SystemOrchestrator()
        orch.register_hook(StartupPhase.ENV_CHECKS, my_hook)
        orch.run_startup_sequence()
        assert calls == ["called"]

    def test_multiple_hooks_for_same_phase(self):
        from core.system_orchestrator import (
            SystemOrchestrator, StartupPhase, PhaseResult, PhaseStatus,
        )
        calls = []

        def hook_a() -> PhaseResult:
            calls.append("a")
            return PhaseResult(phase=StartupPhase.RESOLVE_MODE, status=PhaseStatus.OK)

        def hook_b() -> PhaseResult:
            calls.append("b")
            return PhaseResult(phase=StartupPhase.RESOLVE_MODE, status=PhaseStatus.OK)

        orch = SystemOrchestrator()
        orch.register_hook(StartupPhase.RESOLVE_MODE, hook_a)
        orch.register_hook(StartupPhase.RESOLVE_MODE, hook_b)
        orch.run_startup_sequence()
        assert "a" in calls and "b" in calls

    def test_hook_raising_exception_is_caught(self):
        from core.system_orchestrator import (
            SystemOrchestrator, StartupPhase, PhaseResult, PhaseStatus,
        )

        def bad_hook() -> PhaseResult:
            raise RuntimeError("hook failure")

        orch = SystemOrchestrator()
        orch.register_hook(StartupPhase.ENV_CHECKS, bad_hook)
        # Must not raise
        summary = orch.run_startup_sequence()
        assert summary is not None


# ===========================================================================
# 8. main.py orchestrator authority
# ===========================================================================

class TestMainPyOrchestrator:
    def test_main_py_exists(self):
        assert (PROJECT_ROOT / "main.py").exists()

    def test_main_py_has_system_orchestrator_authority(self):
        content = (PROJECT_ROOT / "main.py").read_text()
        assert "SYSTEM_ORCHESTRATOR_AUTHORITY" in content, (
            "main.py must declare SYSTEM_ORCHESTRATOR_AUTHORITY"
        )

    def test_main_py_references_unified_launcher(self):
        content = (PROJECT_ROOT / "main.py").read_text()
        assert "unified_launcher" in content, (
            "main.py must reference unified_launcher as subordinate component"
        )

    def test_main_py_imports_successfully(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "main_entry", str(PROJECT_ROOT / "main.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert callable(getattr(mod, "main", None))

    def test_main_py_authority_sentinel_matches_orchestrator(self):
        """main.py SYSTEM_ORCHESTRATOR_AUTHORITY must match the orchestrator module."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "main_entry", str(PROJECT_ROOT / "main.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        from core.system_orchestrator import SYSTEM_ORCHESTRATOR_AUTHORITY as orch_sentinel
        main_sentinel = getattr(mod, "SYSTEM_ORCHESTRATOR_AUTHORITY", None)
        assert main_sentinel is not None
        # Both must reference the orchestrator role
        assert "SYSTEM_ORCHESTRATOR" in main_sentinel
        assert "SYSTEM_ORCHESTRATOR" in orch_sentinel

    def test_main_py_has_staged_startup_comment_or_doc(self):
        """main.py docstring/comments must reflect staged bring-up contract."""
        content = (PROJECT_ROOT / "main.py").read_text()
        # Should reference phases or staged bring-up
        has_phases = any(kw in content for kw in ("Phase", "LOAD_CONFIG", "staged", "bring-up"))
        assert has_phases, (
            "main.py must describe the staged bring-up contract"
        )

    def test_main_py_run_orchestrator_preflight_callable(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "main_entry", str(PROJECT_ROOT / "main.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert callable(getattr(mod, "_run_orchestrator_preflight", None)), (
            "main.py must define _run_orchestrator_preflight()"
        )


# ===========================================================================
# 9. unified_launcher.py — subordinate role
# ===========================================================================

class TestUnifiedLauncherSubordinate:
    def test_unified_launcher_exists(self):
        assert (PROJECT_ROOT / "unified_launcher.py").exists()

    def test_unified_launcher_docstring_marks_subordinate(self):
        import ast
        src = (PROJECT_ROOT / "unified_launcher.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        doc = ast.get_docstring(tree) or ""
        doc_lower = doc.lower()
        assert any(
            kw in doc_lower or kw in doc
            for kw in ("subordinate", "从属", "not a top-level", "not.*competing")
        ), (
            "unified_launcher.py docstring must acknowledge its subordinate role (PR-2)"
        )

    def test_unified_launcher_importable(self):
        import importlib
        mod = importlib.import_module("unified_launcher")
        assert mod is not None

    def test_unified_launcher_main_callable(self):
        import importlib
        mod = importlib.import_module("unified_launcher")
        assert callable(getattr(mod, "main", None))


# ===========================================================================
# 10. System mode resolution
# ===========================================================================

class TestSystemModeResolution:
    def test_default_mode_is_local(self, monkeypatch):
        monkeypatch.delenv("GALAXY_SYSTEM_MODE", raising=False)
        monkeypatch.delenv("GALAXY_NATS_URL", raising=False)
        monkeypatch.delenv("GALAXY_CROSS_DEVICE_ENABLED", raising=False)
        from core.system_orchestrator import SystemOrchestrator
        orch = SystemOrchestrator()
        result = orch._run_phase_2_resolve_mode()
        assert result.data.get("system_mode") == "desktop-local"

    def test_cross_device_mode_when_env_set(self, monkeypatch):
        monkeypatch.delenv("GALAXY_SYSTEM_MODE", raising=False)
        monkeypatch.delenv("GALAXY_NATS_URL", raising=False)
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "true")
        from core.system_orchestrator import SystemOrchestrator
        orch = SystemOrchestrator()
        result = orch._run_phase_2_resolve_mode()
        assert result.data.get("system_mode") == "desktop-cross-device"

    def test_cross_device_inferred_from_nats_url(self, monkeypatch):
        monkeypatch.delenv("GALAXY_SYSTEM_MODE", raising=False)
        monkeypatch.delenv("GALAXY_CROSS_DEVICE_ENABLED", raising=False)
        monkeypatch.setenv("GALAXY_NATS_URL", "nats://192.168.1.50:4222")
        from core.system_orchestrator import SystemOrchestrator
        orch = SystemOrchestrator()
        result = orch._run_phase_2_resolve_mode()
        assert result.data.get("system_mode") == "desktop-cross-device"

    def test_explicit_system_mode_env_respected(self, monkeypatch):
        monkeypatch.delenv("GALAXY_NATS_URL", raising=False)
        monkeypatch.delenv("GALAXY_CROSS_DEVICE_ENABLED", raising=False)
        monkeypatch.setenv("GALAXY_SYSTEM_MODE", "desktop-local")
        from core.system_orchestrator import SystemOrchestrator
        orch = SystemOrchestrator()
        result = orch._run_phase_2_resolve_mode()
        assert result.data.get("system_mode") == "desktop-local"
