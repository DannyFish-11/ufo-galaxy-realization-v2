"""Tests for scripts/check_repo_hygiene.py.

These tests cover the hygiene checker in isolation using temporary
directory fixtures — no network or Git access required.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# Make the scripts package importable regardless of how pytest is invoked.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_repo_hygiene import (  # noqa: E402
    ALLOWLIST,
    HygieneReport,
    Violation,
    _is_inside_nodes,
    main,
    scan_repository,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_tree(base: Path, spec: dict) -> None:
    """Recursively create files/dirs described by *spec* under *base*.

    Values of ``None`` create an empty file; dict values create subdirs.
    """
    for name, content in spec.items():
        target = base / name
        if isinstance(content, dict):
            target.mkdir(parents=True, exist_ok=True)
            make_tree(target, content)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content or "")


# ---------------------------------------------------------------------------
# Unit tests — _is_inside_nodes
# ---------------------------------------------------------------------------


class TestIsInsideNodes:
    def test_direct_child(self):
        assert _is_inside_nodes("nodes/Node_01_Foo/main.py") is True

    def test_nested(self):
        assert _is_inside_nodes("nodes/Node_01_Foo/data/file.db") is True

    def test_not_nodes(self):
        assert _is_inside_nodes("core/something.py") is False

    def test_root_level(self):
        assert _is_inside_nodes("main.py") is False

    def test_nodes_prefix_false_positive(self):
        # "nodes_extra/…" must not match
        assert _is_inside_nodes("nodes_extra/Node_01/main.py") is False


# ---------------------------------------------------------------------------
# Unit tests — HygieneReport
# ---------------------------------------------------------------------------


class TestHygieneReport:
    def test_empty_report_is_ok(self):
        r = HygieneReport()
        assert r.ok is True

    def test_add_violation_marks_not_ok(self):
        r = HygieneReport()
        r.add("nodes/Node_01/node.pid", "pid_file", "PID files must not be committed")
        assert r.ok is False
        assert len(r.violations) == 1

    def test_violation_fields(self):
        r = HygieneReport()
        r.add("path/to/file.log", "log_file", "reason")
        v = r.violations[0]
        assert isinstance(v, Violation)
        assert v.rel_path == "path/to/file.log"
        assert v.category == "log_file"
        assert v.reason == "reason"


# ---------------------------------------------------------------------------
# Integration tests — scan_repository
# ---------------------------------------------------------------------------


class TestScanRepository:
    # --- PID files ---

    def test_pid_file_in_nodes_is_violation(self, tmp_path):
        make_tree(tmp_path, {"nodes": {"Node_01": {"node.pid": None, "main.py": ""}}})
        report = scan_repository(str(tmp_path))
        assert not report.ok
        paths = [v.rel_path for v in report.violations]
        assert any("node.pid" in p for p in paths)

    def test_pid_file_at_root_is_violation(self, tmp_path):
        make_tree(tmp_path, {"server.pid": None, "main.py": ""})
        report = scan_repository(str(tmp_path))
        assert not report.ok
        assert any("server.pid" in v.rel_path for v in report.violations)

    # --- Log files ---

    def test_log_file_in_nodes_is_violation(self, tmp_path):
        make_tree(tmp_path, {"nodes": {"Node_02": {"app.log": None, "main.py": ""}}})
        report = scan_repository(str(tmp_path))
        assert not report.ok
        assert any("app.log" in v.rel_path for v in report.violations)

    def test_log_file_outside_nodes_not_flagged(self, tmp_path):
        # *.log outside nodes/ is not flagged by the checker
        # (covered by .gitignore instead)
        make_tree(tmp_path, {"logs": {"system.log": None}, "main.py": ""})
        report = scan_repository(str(tmp_path))
        assert report.ok, report.violations

    # --- Runtime databases ---

    def test_db_file_in_nodes_is_violation(self, tmp_path):
        make_tree(tmp_path, {"nodes": {"Node_03": {"data": {"router.db": None}}}})
        report = scan_repository(str(tmp_path))
        assert not report.ok
        assert any(".db" in v.rel_path for v in report.violations)

    def test_sqlite_file_in_nodes_is_violation(self, tmp_path):
        make_tree(tmp_path, {"nodes": {"Node_04": {"state.sqlite": None}}})
        report = scan_repository(str(tmp_path))
        assert not report.ok
        assert any(".sqlite" in v.rel_path for v in report.violations)

    def test_db_file_outside_nodes_not_flagged(self, tmp_path):
        # A .db at repo root is not flagged (different policy)
        make_tree(tmp_path, {"some.db": None, "main.py": ""})
        report = scan_repository(str(tmp_path))
        assert report.ok, report.violations

    # --- Compiled Python ---

    def test_pyc_file_is_violation(self, tmp_path):
        make_tree(tmp_path, {"core": {"module.pyc": None}})
        report = scan_repository(str(tmp_path))
        assert not report.ok
        assert any(".pyc" in v.rel_path for v in report.violations)

    # --- Temp files ---

    def test_tmp_file_is_violation(self, tmp_path):
        make_tree(tmp_path, {"scratch.tmp": None})
        report = scan_repository(str(tmp_path))
        assert not report.ok
        assert any(".tmp" in v.rel_path for v in report.violations)

    # --- Cache directories ---

    def test_pycache_dir_is_violation(self, tmp_path):
        make_tree(tmp_path, {"core": {"__pycache__": {"module.cpython-311.pyc": None}}})
        report = scan_repository(str(tmp_path))
        assert not report.ok
        assert any("__pycache__" in v.rel_path for v in report.violations)

    def test_pytest_cache_dir_is_violation(self, tmp_path):
        make_tree(tmp_path, {".pytest_cache": {"v": {"cache": {"lastfailed": "{}"}}}})
        report = scan_repository(str(tmp_path))
        assert not report.ok
        assert any(".pytest_cache" in v.rel_path for v in report.violations)

    # --- Clean trees ---

    def test_clean_nodes_tree_passes(self, tmp_path):
        make_tree(
            tmp_path,
            {
                "nodes": {
                    "Node_01": {
                        "main.py": "print('hello')",
                        "fusion_entry.py": "",
                        "requirements.txt": "",
                        "Dockerfile": "",
                        "README.md": "",
                    }
                }
            },
        )
        report = scan_repository(str(tmp_path))
        assert report.ok, report.violations

    def test_clean_repo_root_passes(self, tmp_path):
        make_tree(tmp_path, {"main.py": "", "README.md": "", "core": {"util.py": ""}})
        report = scan_repository(str(tmp_path))
        assert report.ok, report.violations

    # --- Allowlist ---

    def test_allowlisted_path_not_flagged(self, tmp_path, monkeypatch):
        make_tree(tmp_path, {"nodes": {"Node_01": {"fixtures": {"example.db": None}}}})
        monkeypatch.setattr(
            "check_repo_hygiene.ALLOWLIST",
            ["nodes/Node_01/fixtures/example.db"],
        )
        report = scan_repository(str(tmp_path))
        assert report.ok, report.violations

    # --- Subtree restriction ---

    def test_subtree_only_scans_given_dir(self, tmp_path):
        make_tree(
            tmp_path,
            {
                "nodes": {"Node_01": {"node.pid": None}},
                "other": {"fine.py": ""},
            },
        )
        # Scan only "other" — should find no violations
        report = scan_repository(str(tmp_path), subtree="other")
        assert report.ok, report.violations

    def test_subtree_nodes_scans_pid(self, tmp_path):
        make_tree(tmp_path, {"nodes": {"Node_01": {"node.pid": None}}})
        report = scan_repository(str(tmp_path), subtree="nodes")
        assert not report.ok

    # --- .git directory skipped ---

    def test_git_dir_skipped(self, tmp_path):
        make_tree(tmp_path, {".git": {"COMMIT_EDITMSG": "some content"}})
        # No actual violations from a git dir
        report = scan_repository(str(tmp_path))
        assert report.ok, report.violations

    # --- Category tagging ---

    def test_violation_has_correct_category_pid(self, tmp_path):
        make_tree(tmp_path, {"nodes": {"N": {"run.pid": None}}})
        report = scan_repository(str(tmp_path))
        cats = {v.category for v in report.violations}
        assert "pid_file" in cats

    def test_violation_has_correct_category_cache(self, tmp_path):
        make_tree(tmp_path, {"src": {"__pycache__": {"x.pyc": None}}})
        report = scan_repository(str(tmp_path))
        cats = {v.category for v in report.violations}
        assert "cache_dir" in cats


# ---------------------------------------------------------------------------
# CLI tests — main()
# ---------------------------------------------------------------------------


class TestMain:
    def test_main_exit_0_on_clean_tree(self, tmp_path):
        make_tree(tmp_path, {"main.py": "", "nodes": {"Node_01": {"main.py": ""}}})
        rc = main(["--root", str(tmp_path)])
        assert rc == 0

    def test_main_exit_1_on_violation(self, tmp_path):
        make_tree(tmp_path, {"nodes": {"Node_01": {"run.pid": None}}})
        rc = main(["--root", str(tmp_path)])
        assert rc == 1

    def test_main_json_output_ok(self, tmp_path, capsys):
        make_tree(tmp_path, {"nodes": {"Node_01": {"main.py": ""}}})
        rc = main(["--root", str(tmp_path), "--json"])
        assert rc == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is True
        assert data["violation_count"] == 0

    def test_main_json_output_violation(self, tmp_path, capsys):
        make_tree(tmp_path, {"nodes": {"Node_01": {"run.pid": None}}})
        rc = main(["--root", str(tmp_path), "--json"])
        assert rc == 1
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is False
        assert data["violation_count"] >= 1
        paths = [v["path"] for v in data["violations"]]
        assert any("run.pid" in p for p in paths)

    def test_main_subtree_arg(self, tmp_path):
        make_tree(
            tmp_path,
            {
                "nodes": {"Node_01": {"run.pid": None}},
                "core": {"util.py": ""},
            },
        )
        # Restrict scan to core/ — should pass
        rc = main(["--root", str(tmp_path), "core"])
        assert rc == 0

    def test_script_is_executable_via_subprocess(self, tmp_path):
        """Run the script as a subprocess to verify the CLI entry point works."""
        make_tree(tmp_path, {"nodes": {"Node_01": {"main.py": ""}}})
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "check_repo_hygiene.py"), "--root", str(tmp_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Smoke test against the actual repository
# ---------------------------------------------------------------------------


class TestActualRepository:
    def test_nodes_directory_is_clean(self):
        """After removing committed artifacts, the nodes/ directory must pass hygiene."""
        nodes_dir = REPO_ROOT / "nodes"
        if not nodes_dir.is_dir():
            pytest.skip("nodes/ directory not found")
        report = scan_repository(str(REPO_ROOT), subtree="nodes")
        assert report.ok, (
            f"nodes/ has hygiene violations — fix them before merging:\n"
            + "\n".join(f"  {v.rel_path}  [{v.category}]  {v.reason}" for v in report.violations)
        )
