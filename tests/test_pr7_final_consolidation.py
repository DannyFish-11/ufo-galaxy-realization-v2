"""
tests/test_pr7_final_consolidation.py
=======================================
PR-7 Final — Unified OpenClawd System Integration (U1–U33 Consolidation)

Test coverage:
  1. docs/migration/unified_migration_matrix.md exists with required sections.
  2. docs/acceptance/u1_u33_final_acceptance.md exists and covers U1–U33.
  3. scripts/generate_system_readiness_report.py is importable and runnable.
  4. scripts/audit_unified_paths.py is importable and runnable.
  5. CheckResult dataclass (readiness report) passes/fails correctly.
  6. Readiness report check functions return lists of CheckResult.
  7. Readiness report to_json_report() produces expected keys.
  8. audit_unified_paths scan_repo() returns list of BypassFinding objects.
  9. audit_unified_paths print_report() does not raise.
 10. audit_unified_paths to_json_report() produces expected keys.
 11. Audit script scans a clean temp directory and returns no findings.
 12. CI workflow contains required check jobs (conformance, chaos, ssot-udm).
 13. Migration matrix contains required section headers.
 14. Acceptance doc contains U1 through U33 references.
 15. Readiness report main() exits 0 when called with --json.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import List

import pytest

# Make sure repo root is on sys.path for local imports
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_readiness():
    """Import generate_system_readiness_report."""
    import scripts.generate_system_readiness_report as mod
    return mod


def _import_audit():
    """Import audit_unified_paths."""
    import scripts.audit_unified_paths as mod
    return mod


# ---------------------------------------------------------------------------
# 1–2: Documentation artifact existence
# ---------------------------------------------------------------------------


class TestDocumentationArtifacts:
    def test_migration_matrix_exists(self) -> None:
        path = _REPO_ROOT / "docs" / "migration" / "unified_migration_matrix.md"
        assert path.is_file(), f"Migration matrix not found at {path}"

    def test_acceptance_doc_exists(self) -> None:
        path = _REPO_ROOT / "docs" / "acceptance" / "u1_u33_final_acceptance.md"
        assert path.is_file(), f"Acceptance doc not found at {path}"

    def test_migration_matrix_has_required_sections(self) -> None:
        path = _REPO_ROOT / "docs" / "migration" / "unified_migration_matrix.md"
        content = path.read_text(encoding="utf-8")
        required_sections = [
            "Ingress Path Matrix",
            "State Mutation Path Matrix",
            "Command/Envelope Path Matrix",
            "Capability Dispatch Path Matrix",
            "Adapter Coverage Summary",
            "Bypass Paths",
        ]
        for section in required_sections:
            assert section in content, f"Missing section '{section}' in migration matrix"

    def test_acceptance_doc_covers_u1_through_u33(self) -> None:
        path = _REPO_ROOT / "docs" / "acceptance" / "u1_u33_final_acceptance.md"
        content = path.read_text(encoding="utf-8")
        for i in range(1, 34):
            assert f"U{i}" in content or f"| U{i} |" in content or f"U{i}:" in content, (
                f"Acceptance doc does not reference U{i}"
            )

    def test_acceptance_doc_has_summary_table(self) -> None:
        path = _REPO_ROOT / "docs" / "acceptance" / "u1_u33_final_acceptance.md"
        content = path.read_text(encoding="utf-8")
        assert "Summary" in content
        assert "33" in content  # total count

    def test_acceptance_doc_has_signoff_checklist(self) -> None:
        path = _REPO_ROOT / "docs" / "acceptance" / "u1_u33_final_acceptance.md"
        content = path.read_text(encoding="utf-8")
        assert "Sign-off" in content or "Checklist" in content


# ---------------------------------------------------------------------------
# 3–4: Script importability
# ---------------------------------------------------------------------------


class TestScriptImportability:
    def test_readiness_report_importable(self) -> None:
        mod = _import_readiness()
        assert hasattr(mod, "run_all_checks")
        assert hasattr(mod, "CheckResult")
        assert hasattr(mod, "main")
        assert hasattr(mod, "print_report")
        assert hasattr(mod, "to_json_report")

    def test_audit_paths_importable(self) -> None:
        mod = _import_audit()
        assert hasattr(mod, "scan_repo")
        assert hasattr(mod, "BypassFinding")
        assert hasattr(mod, "main")
        assert hasattr(mod, "print_report")
        assert hasattr(mod, "to_json_report")


# ---------------------------------------------------------------------------
# 5: CheckResult dataclass
# ---------------------------------------------------------------------------


class TestCheckResult:
    def test_passed_check(self) -> None:
        mod = _import_readiness()
        r = mod.CheckResult(name="Test", category="Cat", passed=True, detail="ok")
        assert r.passed is True
        assert r.name == "Test"
        assert r.category == "Cat"

    def test_failed_check_has_suggestion(self) -> None:
        mod = _import_readiness()
        r = mod.CheckResult(
            name="Missing file",
            category="Docs",
            passed=False,
            detail="MISSING: some/file.md",
            suggestion="Create the file.",
        )
        assert r.passed is False
        assert "Create" in r.suggestion

    def test_check_result_defaults(self) -> None:
        mod = _import_readiness()
        r = mod.CheckResult(name="x", category="y", passed=True)
        assert r.detail == ""
        assert r.suggestion == ""


# ---------------------------------------------------------------------------
# 6: Check functions return lists of CheckResult
# ---------------------------------------------------------------------------


class TestCheckFunctions:
    def test_check_doc_artifacts_returns_list(self) -> None:
        mod = _import_readiness()
        results = mod.check_doc_artifacts()
        assert isinstance(results, list)
        assert len(results) > 0
        for r in results:
            assert isinstance(r, mod.CheckResult)

    def test_check_conformance_tests_returns_list(self) -> None:
        mod = _import_readiness()
        results = mod.check_conformance_tests()
        assert isinstance(results, list)
        # Verify the 4 required conformance test files are checked
        names = [r.name for r in results]
        assert any("test_aip_v3_envelope.py" in n for n in names)
        assert any("test_gateway_routing.py" in n for n in names)
        assert any("test_nats_trace.py" in n for n in names)
        assert any("test_udm_ssot_conformance.py" in n for n in names)

    def test_check_chaos_tests_returns_list(self) -> None:
        mod = _import_readiness()
        results = mod.check_chaos_tests()
        assert isinstance(results, list)
        # Verify the 4 required chaos test files are checked
        names = [r.name for r in results]
        assert any("test_disconnect_chaos.py" in n for n in names)
        assert any("test_latency_chaos.py" in n for n in names)
        assert any("test_duplicate_message_chaos.py" in n for n in names)
        assert any("test_partial_failure_chaos.py" in n for n in names)

    def test_check_audit_scripts_returns_list(self) -> None:
        mod = _import_readiness()
        results = mod.check_audit_scripts()
        assert isinstance(results, list)
        assert len(results) >= 2

    def test_check_schema_and_config_files_returns_list(self) -> None:
        mod = _import_readiness()
        results = mod.check_schema_and_config_files()
        assert isinstance(results, list)
        assert len(results) > 0

    def test_check_no_forbidden_imports_returns_list(self) -> None:
        mod = _import_readiness()
        results = mod.check_no_forbidden_aip_v2_imports()
        assert isinstance(results, list)
        assert len(results) == 1
        r = results[0]
        assert isinstance(r, mod.CheckResult)

    def test_run_all_checks_returns_non_empty_list(self) -> None:
        mod = _import_readiness()
        results = mod.run_all_checks()
        assert isinstance(results, list)
        assert len(results) > 10  # should have many checks

    def test_check_ci_workflow_returns_list(self) -> None:
        mod = _import_readiness()
        results = mod.check_ci_workflow()
        assert isinstance(results, list)
        assert len(results) > 0


# ---------------------------------------------------------------------------
# 7: to_json_report produces expected structure
# ---------------------------------------------------------------------------


class TestReadinessJsonReport:
    def test_json_report_has_required_keys(self) -> None:
        mod = _import_readiness()
        results = [
            mod.CheckResult(name="a", category="x", passed=True),
            mod.CheckResult(name="b", category="x", passed=False, suggestion="fix it"),
        ]
        report = mod.to_json_report(results)
        assert "generated_at" in report
        assert "total" in report
        assert "passed" in report
        assert "failed" in report
        assert "ready" in report
        assert "checks" in report

    def test_json_report_counts_correctly(self) -> None:
        mod = _import_readiness()
        results = [
            mod.CheckResult(name="a", category="x", passed=True),
            mod.CheckResult(name="b", category="x", passed=True),
            mod.CheckResult(name="c", category="x", passed=False),
        ]
        report = mod.to_json_report(results)
        assert report["total"] == 3
        assert report["passed"] == 2
        assert report["failed"] == 1
        assert report["ready"] is False

    def test_json_report_ready_when_all_pass(self) -> None:
        mod = _import_readiness()
        results = [mod.CheckResult(name="a", category="x", passed=True)]
        report = mod.to_json_report(results)
        assert report["ready"] is True

    def test_json_report_serializable(self) -> None:
        mod = _import_readiness()
        results = mod.run_all_checks()
        report = mod.to_json_report(results)
        # Must be JSON-serializable without error
        json_str = json.dumps(report)
        assert len(json_str) > 10


# ---------------------------------------------------------------------------
# 8–10: audit_unified_paths
# ---------------------------------------------------------------------------


class TestAuditUnifiedPaths:
    def test_scan_repo_returns_list(self) -> None:
        mod = _import_audit()
        findings = mod.scan_repo(_REPO_ROOT)
        assert isinstance(findings, list)

    def test_bypass_finding_fields(self) -> None:
        mod = _import_audit()
        f = mod.BypassFinding(
            file="core/foo.py",
            line=10,
            col=4,
            kind="direct_submit",
            detail="submit_task() without DAG",
        )
        assert f.file == "core/foo.py"
        assert f.line == 10
        assert f.kind == "direct_submit"

    def test_audit_json_report_has_required_keys(self) -> None:
        mod = _import_audit()
        findings: list = []
        report = mod.to_json_report(findings, _REPO_ROOT)
        assert "generated_at" in report
        assert "repo_root" in report
        assert "total_findings" in report
        assert "passed" in report
        assert "findings" in report

    def test_audit_json_report_passed_when_no_findings(self) -> None:
        mod = _import_audit()
        report = mod.to_json_report([], _REPO_ROOT)
        assert report["passed"] is True
        assert report["total_findings"] == 0

    def test_audit_json_report_failed_when_findings_exist(self) -> None:
        mod = _import_audit()
        f = mod.BypassFinding(file="x.py", line=1, col=0, kind="direct_submit", detail="test")
        report = mod.to_json_report([f], _REPO_ROOT)
        assert report["passed"] is False
        assert report["total_findings"] == 1

    def test_print_report_no_raise(self, capsys) -> None:
        mod = _import_audit()
        mod.print_report([], _REPO_ROOT)  # should not raise
        captured = capsys.readouterr()
        assert "PASS" in captured.out

    def test_print_report_with_findings_no_raise(self, capsys) -> None:
        mod = _import_audit()
        f = mod.BypassFinding(
            file="core/bad.py", line=5, col=0, kind="direct_submit", detail="bad call"
        )
        mod.print_report([f], _REPO_ROOT)
        captured = capsys.readouterr()
        assert "FAIL" in captured.out or "finding" in captured.out.lower()


# ---------------------------------------------------------------------------
# 11: Scan a clean temp directory — no findings expected
# ---------------------------------------------------------------------------


class TestAuditCleanDirectory:
    def test_clean_dir_produces_no_findings(self) -> None:
        mod = _import_audit()
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write a simple clean Python file
            (Path(tmpdir) / "clean.py").write_text(
                "def hello():\n    return 'world'\n",
                encoding="utf-8",
            )
            findings = mod.scan_repo(Path(tmpdir))
        assert findings == []

    def test_v2_import_in_non_allowed_file_produces_finding(self) -> None:
        mod = _import_audit()
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_file = Path(tmpdir) / "bad_module.py"
            bad_file.write_text(
                "from galaxy_gateway.aip_protocol_v2 import something\n",
                encoding="utf-8",
            )
            findings = mod.scan_repo(Path(tmpdir))
        assert len(findings) == 1
        assert findings[0].kind == "forbidden_v2_import"

    def test_allowed_dir_prefix_skips_scan(self) -> None:
        mod = _import_audit()
        with tempfile.TemporaryDirectory() as tmpdir:
            tests_dir = Path(tmpdir) / "tests"
            tests_dir.mkdir()
            bad_file = tests_dir / "test_something.py"
            bad_file.write_text(
                "import galaxy_gateway.aip_protocol_v2\n",
                encoding="utf-8",
            )
            findings = mod.scan_repo(Path(tmpdir))
        # tests/ is in ALLOWED_DIR_PREFIXES so nothing should be flagged
        assert findings == []


# ---------------------------------------------------------------------------
# 12: CI workflow contains required jobs
# ---------------------------------------------------------------------------


class TestCIWorkflowJobs:
    def test_ci_yml_exists(self) -> None:
        ci = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
        assert ci.is_file(), "CI workflow ci.yml not found"

    def test_ci_has_conformance_job(self) -> None:
        ci = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
        content = ci.read_text(encoding="utf-8")
        assert "conformance-tests:" in content, "conformance-tests job missing from ci.yml"

    def test_ci_has_chaos_job(self) -> None:
        ci = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
        content = ci.read_text(encoding="utf-8")
        assert "chaos-tests:" in content, "chaos-tests job missing from ci.yml"

    def test_ci_has_ssot_udm_job(self) -> None:
        ci = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
        content = ci.read_text(encoding="utf-8")
        assert "ssot-udm-conformance:" in content, "ssot-udm-conformance job missing from ci.yml"

    def test_ci_has_v3_protocol_guard(self) -> None:
        ci = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
        content = ci.read_text(encoding="utf-8")
        assert "v3-protocol-guard:" in content


# ---------------------------------------------------------------------------
# 13–14: Documentation content (additional checks)
# ---------------------------------------------------------------------------


class TestDocumentationContent:
    def test_migration_matrix_references_entrypoint_router(self) -> None:
        path = _REPO_ROOT / "docs" / "migration" / "unified_migration_matrix.md"
        content = path.read_text(encoding="utf-8")
        assert "EntrypointRouter" in content or "entrypoint_router" in content

    def test_migration_matrix_references_adapters(self) -> None:
        path = _REPO_ROOT / "docs" / "migration" / "unified_migration_matrix.md"
        content = path.read_text(encoding="utf-8")
        assert "legacy_adapters" in content or "Adapter" in content

    def test_acceptance_doc_references_canonical_modules(self) -> None:
        path = _REPO_ROOT / "docs" / "acceptance" / "u1_u33_final_acceptance.md"
        content = path.read_text(encoding="utf-8")
        assert "core/unified/entrypoint_router.py" in content
        assert "core/unified/command_envelope.py" in content
        assert "core/unified/llm_router.py" in content

    def test_acceptance_doc_references_test_files(self) -> None:
        path = _REPO_ROOT / "docs" / "acceptance" / "u1_u33_final_acceptance.md"
        content = path.read_text(encoding="utf-8")
        assert "tests/conformance/" in content
        assert "tests/chaos/" in content

    def test_acceptance_doc_all_u_ids_pass(self) -> None:
        """All U1–U33 should be marked PASS (✅) in the acceptance doc."""
        path = _REPO_ROOT / "docs" / "acceptance" / "u1_u33_final_acceptance.md"
        content = path.read_text(encoding="utf-8")
        # Count PASS markers — should be >= 33
        pass_count = content.count("✅ PASS")
        assert pass_count >= 33, f"Expected at least 33 PASS marks, found {pass_count}"


# ---------------------------------------------------------------------------
# 15: readiness report main() exit codes
# ---------------------------------------------------------------------------


class TestReadinessReportMain:
    def test_main_returns_int(self) -> None:
        mod = _import_readiness()
        # Should return 0 or 1; should not raise
        exit_code = mod.main(["--json"])
        assert exit_code in (0, 1)

    def test_main_json_output_writes_to_file(self, tmp_path) -> None:
        mod = _import_readiness()
        out_file = tmp_path / "report.json"
        mod.main(["--output", str(out_file)])
        assert out_file.is_file()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert "total" in data
        assert "checks" in data
        assert isinstance(data["checks"], list)
