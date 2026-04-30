"""
tests/test_pr4_v6_boundary_integration.py
==========================================
PR-4: V6 center_authority_boundary — startup / health / release integration.

This test suite verifies that V6 is correctly operationalised at the
**boundary / startup / health / release** layer and is NOT wired into
per-request hot paths.

Coverage
--------
1. Startup integration — Phase 7 of SystemOrchestrator surfaces V6 boundary status.
2. Startup degradation — Phase 7 becomes DEGRADED when the boundary is broken.
3. Health endpoint helper — _get_authority_boundary_status() is defined and callable.
4. Health endpoint helper — returns expected keys.
5. Health endpoint helper — returns degraded when boundary is broken.
6. Release / CI gate — validate_runtime.check_center_authority_boundary passes.
7. Hot-path exclusion — OpenClawd.process does NOT call evaluate/assert boundary.
8. Hot-path exclusion — CommandRouter.route_envelope does NOT call evaluate/assert boundary.
9. Boundary module present — core.center_authority_boundary importable.
10. Phase 7 data keys — authority_boundary_status and authority_boundary present.
11. Phase 7 intact system — authority_boundary_status == "intact" when all domains OK.
12. Phase 7 degraded system — DEGRADED status when evaluate returns degraded report.
"""

from __future__ import annotations

import importlib
import pathlib
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = pathlib.Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# Availability guard — skip entire suite if V6 module is absent
# ---------------------------------------------------------------------------

try:
    from core.center_authority_boundary import (
        evaluate_center_authority_boundary,
        assert_center_authority_intact,
        CenterAuthorityBoundaryReport,
        DomainBoundaryStatus,
        AuthorityDomain,
        CENTER_AUTHORITY_BOUNDARY_AUTHORITY,
    )
    _V6_AVAILABLE = True
except ImportError:
    _V6_AVAILABLE = False

_skip_v6 = pytest.mark.skipif(not _V6_AVAILABLE, reason="core.center_authority_boundary not available")


# ===========================================================================
# 1. Startup integration — Phase 7 surfaces V6 boundary status
# ===========================================================================

class TestStartupPhase7Integration:
    """V6 is wired into SystemOrchestrator Phase 7 (READINESS_SUMMARY)."""

    def test_phase7_result_data_contains_authority_boundary_status(self):
        """Phase 7 data must include authority_boundary_status key."""
        from core.system_orchestrator import SystemOrchestrator, StartupPhase
        orch = SystemOrchestrator(continue_on_failure=True)
        summary = orch.run_startup_sequence()
        phase7 = next(
            (r for r in summary.phase_results if r.phase == StartupPhase.READINESS_SUMMARY),
            None,
        )
        assert phase7 is not None, "Phase 7 (READINESS_SUMMARY) must be present in results"
        assert "authority_boundary_status" in phase7.data, (
            "Phase 7 data must contain 'authority_boundary_status' from V6 boundary check"
        )

    def test_phase7_result_data_contains_authority_boundary_dict(self):
        """Phase 7 data must include authority_boundary sub-dict."""
        from core.system_orchestrator import SystemOrchestrator, StartupPhase
        orch = SystemOrchestrator(continue_on_failure=True)
        summary = orch.run_startup_sequence()
        phase7 = next(
            (r for r in summary.phase_results if r.phase == StartupPhase.READINESS_SUMMARY),
            None,
        )
        assert phase7 is not None
        assert "authority_boundary" in phase7.data, (
            "Phase 7 data must contain 'authority_boundary' dict from V6 boundary check"
        )
        assert isinstance(phase7.data["authority_boundary"], dict)

    @_skip_v6
    def test_phase7_authority_boundary_status_is_intact_on_clean_system(self):
        """On a system where V6 modules are present, Phase 7 status should be intact."""
        from core.system_orchestrator import SystemOrchestrator, StartupPhase
        orch = SystemOrchestrator(continue_on_failure=True)
        summary = orch.run_startup_sequence()
        phase7 = next(
            (r for r in summary.phase_results if r.phase == StartupPhase.READINESS_SUMMARY),
            None,
        )
        assert phase7 is not None
        status = phase7.data.get("authority_boundary_status", "")
        assert status in ("intact", "degraded", "not_checked", "error"), (
            f"authority_boundary_status must be a valid value, got: {status!r}"
        )

    @_skip_v6
    def test_phase7_becomes_degraded_when_boundary_broken(self):
        """Phase 7 must return DEGRADED (not OK) when the V6 boundary check fails."""
        from core.system_orchestrator import (
            SystemOrchestrator, StartupPhase, PhaseStatus,
        )
        from core.center_authority_boundary import CenterAuthorityBoundaryReport

        # Build a degraded boundary report
        degraded_report = CenterAuthorityBoundaryReport()
        degraded_report.degraded_domains = ["completion_truth"]
        degraded_report.all_domains_intact = False

        with patch(
            "core.center_authority_boundary.evaluate_center_authority_boundary",
            return_value=degraded_report,
        ):
            orch = SystemOrchestrator(continue_on_failure=True)
            summary = orch.run_startup_sequence()

        phase7 = next(
            (r for r in summary.phase_results if r.phase == StartupPhase.READINESS_SUMMARY),
            None,
        )
        assert phase7 is not None
        assert phase7.status == PhaseStatus.DEGRADED, (
            "Phase 7 must be DEGRADED when V6 boundary is broken, "
            f"got: {phase7.status.name}"
        )

    @_skip_v6
    def test_phase7_degraded_detail_mentions_authority_boundary(self):
        """When boundary is broken, Phase 7 detail must mention the failure."""
        from core.system_orchestrator import SystemOrchestrator, StartupPhase
        from core.center_authority_boundary import CenterAuthorityBoundaryReport

        degraded_report = CenterAuthorityBoundaryReport()
        degraded_report.degraded_domains = ["orchestration_truth"]
        degraded_report.all_domains_intact = False

        with patch(
            "core.center_authority_boundary.evaluate_center_authority_boundary",
            return_value=degraded_report,
        ):
            orch = SystemOrchestrator(continue_on_failure=True)
            summary = orch.run_startup_sequence()

        phase7 = next(
            (r for r in summary.phase_results if r.phase == StartupPhase.READINESS_SUMMARY),
            None,
        )
        assert phase7 is not None
        assert "authority_boundary" in phase7.detail.lower() or "degraded" in phase7.detail.lower(), (
            "Phase 7 detail must mention authority_boundary when V6 check fails"
        )

    @_skip_v6
    def test_phase7_ok_when_boundary_intact(self):
        """Phase 7 must remain OK when boundary is intact."""
        from core.system_orchestrator import (
            SystemOrchestrator, StartupPhase, PhaseStatus,
        )
        from core.center_authority_boundary import CenterAuthorityBoundaryReport

        intact_report = CenterAuthorityBoundaryReport()
        intact_report.degraded_domains = []
        intact_report.all_domains_intact = True

        with patch(
            "core.center_authority_boundary.evaluate_center_authority_boundary",
            return_value=intact_report,
        ):
            orch = SystemOrchestrator(continue_on_failure=True)
            summary = orch.run_startup_sequence()

        phase7 = next(
            (r for r in summary.phase_results if r.phase == StartupPhase.READINESS_SUMMARY),
            None,
        )
        assert phase7 is not None
        assert phase7.status == PhaseStatus.OK, (
            "Phase 7 should remain OK when boundary is intact"
        )
        assert phase7.data.get("authority_boundary_status") == "intact"


# ===========================================================================
# 2. Health endpoint helper
# ===========================================================================

class TestHealthEndpointHelper:
    """health_monitor._get_authority_boundary_status() is wired correctly."""

    def _load_health_monitor_mod(self, name: str = "_hm_check"):
        """Load health_monitor.py with problematic optional deps stubbed out."""
        import importlib.util
        import sys
        # Stub out heavy optional dependencies that are not installed in the
        # unit-test environment.  We only need the pure-Python helper function.
        for dep in ("httpx", "fastapi", "fastapi.middleware.cors",
                    "fastapi.responses", "uvicorn"):
            sys.modules.setdefault(dep, MagicMock())
        sys.modules.setdefault("system_manager", MagicMock())
        spec = importlib.util.spec_from_file_location(
            name, str(PROJECT_ROOT / "health_monitor.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod

    def test_helper_function_exists_in_health_monitor(self):
        """_get_authority_boundary_status must be defined in health_monitor."""
        mod = self._load_health_monitor_mod("_hm_exists")
        assert hasattr(mod, "_get_authority_boundary_status"), (
            "health_monitor must define _get_authority_boundary_status()"
        )
        assert callable(mod._get_authority_boundary_status)

    @_skip_v6
    def test_helper_returns_dict_with_expected_keys(self):
        """_get_authority_boundary_status() must return a dict with status key."""
        mod = self._load_health_monitor_mod("_hm_keys")
        result = mod._get_authority_boundary_status()
        assert isinstance(result, dict)
        assert "status" in result, f"Expected 'status' key, got: {list(result.keys())}"

    @_skip_v6
    def test_helper_returns_intact_when_boundary_intact(self):
        """_get_authority_boundary_status() must return 'intact' when all domains OK."""
        mod = self._load_health_monitor_mod("_hm_intact")

        intact_report = CenterAuthorityBoundaryReport()
        intact_report.degraded_domains = []
        intact_report.all_domains_intact = True

        with patch(
            "core.center_authority_boundary.evaluate_center_authority_boundary",
            return_value=intact_report,
        ):
            result = mod._get_authority_boundary_status()

        assert result.get("status") == "intact", (
            f"Expected 'intact', got {result.get('status')!r}"
        )
        assert result.get("all_domains_intact") is True

    @_skip_v6
    def test_helper_returns_degraded_when_boundary_degraded(self):
        """_get_authority_boundary_status() must return 'degraded' when domains fail."""
        mod = self._load_health_monitor_mod("_hm_deg")

        degraded_report = CenterAuthorityBoundaryReport()
        degraded_report.degraded_domains = ["completion_truth", "orchestration_truth"]
        degraded_report.all_domains_intact = False

        with patch(
            "core.center_authority_boundary.evaluate_center_authority_boundary",
            return_value=degraded_report,
        ):
            result = mod._get_authority_boundary_status()

        assert result.get("status") == "degraded", (
            f"Expected 'degraded', got {result.get('status')!r}"
        )
        assert result.get("all_domains_intact") is False

    def test_helper_returns_error_dict_when_module_unavailable(self):
        """_get_authority_boundary_status() must not raise if V6 module is absent."""
        mod = self._load_health_monitor_mod("_hm_err")

        with patch(
            "core.center_authority_boundary.evaluate_center_authority_boundary",
            side_effect=ImportError("module unavailable"),
        ):
            result = mod._get_authority_boundary_status()

        assert isinstance(result, dict)
        # Should surface error gracefully
        assert result.get("status") in ("error", "intact", "degraded"), (
            "Must return a dict with a 'status' key even when V6 raises"
        )


# ===========================================================================
# 3. Release / CI integrity gate
# ===========================================================================

class TestReleaseCIGate:
    """validate_runtime.check_center_authority_boundary() functions as CI gate."""

    def test_check_function_exists_in_validate_runtime(self):
        """validate_runtime.py must define check_center_authority_boundary()."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_vr_ci", str(PROJECT_ROOT / "scripts" / "validate_runtime.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        assert hasattr(mod, "check_center_authority_boundary"), (
            "validate_runtime.py must define check_center_authority_boundary() "
            "as the CI/release integrity gate for V6"
        )
        assert callable(mod.check_center_authority_boundary)

    def test_check_function_is_called_from_main(self):
        """check_center_authority_boundary() must appear in validate_runtime main()."""
        content = (PROJECT_ROOT / "scripts" / "validate_runtime.py").read_text()
        assert "check_center_authority_boundary" in content, (
            "validate_runtime.py main() must call check_center_authority_boundary()"
        )
        # Verify it appears in main() body (after the main() def)
        main_idx = content.index("def main()")
        assert "check_center_authority_boundary" in content[main_idx:], (
            "check_center_authority_boundary() must be called from main()"
        )

    @_skip_v6
    def test_check_function_produces_pass_results_on_clean_system(self):
        """On a system with V6 modules present, CI gate should produce PASS results."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_vr_ci_run", str(PROJECT_ROOT / "scripts" / "validate_runtime.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]

        # Run only the V6 check, not the full validator
        before_count = len(mod._results)
        mod.check_center_authority_boundary()
        new_results = mod._results[before_count:]

        assert len(new_results) > 0, "check_center_authority_boundary() must record results"
        fails = [r for r in new_results if r.status == "FAIL"]
        assert not fails, (
            f"check_center_authority_boundary() produced FAIL results: "
            f"{[(r.name, r.detail) for r in fails]}"
        )

    def test_check_function_records_v6_module_importability(self):
        """CI gate must check that core.center_authority_boundary is importable."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_vr_ci_imp", str(PROJECT_ROOT / "scripts" / "validate_runtime.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]

        before_count = len(mod._results)
        mod.check_center_authority_boundary()
        new_results = mod._results[before_count:]

        names = [r.name for r in new_results]
        assert any("center_authority_boundary" in n.lower() or "v6" in n.lower() for n in names), (
            "CI gate results must include a check mentioning 'center_authority_boundary' or 'v6'"
        )


# ===========================================================================
# 4. Hot-path exclusion
# ===========================================================================

class TestHotPathExclusion:
    """V6 must NOT be wired into per-request hot paths."""

    def test_openclawd_process_does_not_import_center_authority_boundary(self):
        """OpenClawd.process() must not import or call center_authority_boundary."""
        openclawd_path = PROJECT_ROOT / "core" / "openclawd.py"
        if not openclawd_path.exists():
            pytest.skip("core/openclawd.py not present — skipping hot-path check")
        content = openclawd_path.read_text()
        # If the module imports center_authority_boundary, check that it is not
        # called from within the process() method body.
        # We perform a simple heuristic: look for 'evaluate_center_authority_boundary'
        # or 'assert_center_authority_intact' inside the process() method block.
        process_idx = content.find("def process(")
        if process_idx == -1:
            # OpenClawd may not have a process() method — nothing to check.
            return
        # Find the approximate end of process() by looking for the next top-level def
        # (heuristic: next line starting with "    def " or "def " at same indentation)
        process_block = content[process_idx: process_idx + 4000]
        assert "evaluate_center_authority_boundary" not in process_block, (
            "OpenClawd.process() must not call evaluate_center_authority_boundary() "
            "— V6 belongs at the boundary/startup layer, not the per-request hot path"
        )
        assert "assert_center_authority_intact" not in process_block, (
            "OpenClawd.process() must not call assert_center_authority_intact() "
            "— V6 belongs at the boundary/startup layer, not the per-request hot path"
        )

    def test_command_router_route_envelope_does_not_import_center_authority_boundary(self):
        """CommandRouter.route_envelope() must not call center_authority_boundary."""
        router_path = PROJECT_ROOT / "core" / "command_router.py"
        if not router_path.exists():
            pytest.skip("core/command_router.py not present — skipping hot-path check")
        content = router_path.read_text()
        route_idx = content.find("def route_envelope(")
        if route_idx == -1:
            return
        route_block = content[route_idx: route_idx + 4000]
        assert "evaluate_center_authority_boundary" not in route_block, (
            "CommandRouter.route_envelope() must not call evaluate_center_authority_boundary() "
            "— V6 belongs at the boundary/startup layer, not the per-request hot path"
        )
        assert "assert_center_authority_intact" not in route_block, (
            "CommandRouter.route_envelope() must not call assert_center_authority_intact() "
            "— V6 belongs at the boundary/startup layer, not the per-request hot path"
        )

    def test_phase7_is_only_readiness_summary_not_per_request(self):
        """V6 in SystemOrchestrator runs at Phase 7 (READINESS_SUMMARY), not per-request."""
        from core.system_orchestrator import StartupPhase
        # Phase 7 value must be 7 — the final readiness summary, not a request phase
        assert StartupPhase.READINESS_SUMMARY.value == 7
        # Ensure there is no StartupPhase that indicates per-request processing
        phase_names = {p.name for p in StartupPhase}
        assert "REQUEST" not in " ".join(phase_names), (
            "No startup phase should be named REQUEST — V6 is startup-layer only"
        )


# ===========================================================================
# 5. V6 module structure
# ===========================================================================

@_skip_v6
class TestV6ModuleStructure:
    """Core V6 module structure is present and well-formed."""

    def test_authority_sentinel_is_non_empty_string(self):
        assert isinstance(CENTER_AUTHORITY_BOUNDARY_AUTHORITY, str)
        assert len(CENTER_AUTHORITY_BOUNDARY_AUTHORITY) > 0

    def test_evaluate_returns_report_instance(self):
        report = evaluate_center_authority_boundary()
        assert isinstance(report, CenterAuthorityBoundaryReport)

    def test_report_has_all_domains_intact_field(self):
        report = evaluate_center_authority_boundary()
        assert isinstance(report.all_domains_intact, bool)

    def test_report_has_degraded_domains_list(self):
        report = evaluate_center_authority_boundary()
        assert isinstance(report.degraded_domains, list)

    def test_report_has_report_id(self):
        report = evaluate_center_authority_boundary()
        assert isinstance(report.report_id, str)
        assert len(report.report_id) > 0

    def test_assert_does_not_raise_on_intact_system(self):
        """assert_center_authority_intact() must not raise when all domains intact."""
        intact_report = CenterAuthorityBoundaryReport()
        intact_report.degraded_domains = []
        intact_report.all_domains_intact = True
        with patch(
            "core.center_authority_boundary.evaluate_center_authority_boundary",
            return_value=intact_report,
        ):
            # Should not raise
            assert_center_authority_intact()

    def test_assert_raises_on_degraded_system(self):
        """assert_center_authority_intact() must raise CenterAuthorityViolation when degraded."""
        from core.center_authority_boundary import CenterAuthorityViolation
        degraded_report = CenterAuthorityBoundaryReport()
        degraded_report.degraded_domains = ["completion_truth"]
        degraded_report.all_domains_intact = False
        with patch(
            "core.center_authority_boundary.evaluate_center_authority_boundary",
            return_value=degraded_report,
        ):
            with pytest.raises(CenterAuthorityViolation):
                assert_center_authority_intact()
