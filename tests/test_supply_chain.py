"""
tests/test_supply_chain.py — PR-G4 Supply-Chain Security
=========================================================

Unit tests for:
1.  requirements.hash.txt — presence, format, and --require-hashes compliance.
2.  requirements.in — input file presence and basic syntax.
3.  scripts/pin_deps.sh — existence and executability.
4.  scripts/gen_node_security_report.py — report builder logic.
5.  per-node security report schema validation.
6.  combined security summary schema validation.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Project root helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS_HASH = REPO_ROOT / "requirements.hash.txt"
REQUIREMENTS_IN = REPO_ROOT / "requirements.in"
PIN_DEPS_SH = REPO_ROOT / "scripts" / "pin_deps.sh"
GEN_REPORT_PY = REPO_ROOT / "scripts" / "gen_node_security_report.py"
NODES_DIR = REPO_ROOT / "nodes"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_gen_report():
    """Import gen_node_security_report as a module."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "gen_node_security_report", str(GEN_REPORT_PY)
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ===========================================================================
# 1. requirements.hash.txt
# ===========================================================================


class TestRequirementsHashFile:
    """requirements.hash.txt must exist and be well-formed."""

    def test_hash_file_present(self):
        assert REQUIREMENTS_HASH.exists(), (
            "requirements.hash.txt is missing — run: scripts/pin_deps.sh"
        )

    def test_hash_file_not_empty(self):
        content = REQUIREMENTS_HASH.read_text()
        non_comment_lines = [
            ln for ln in content.splitlines() if ln.strip() and not ln.startswith("#")
        ]
        assert len(non_comment_lines) > 0, "requirements.hash.txt has no package entries"

    def test_hash_file_contains_require_hashes_entries(self):
        """At least one entry must have a --hash=sha256 annotation."""
        content = REQUIREMENTS_HASH.read_text()
        assert "--hash=sha256:" in content, (
            "requirements.hash.txt contains no sha256 hash entries; "
            "regenerate with: scripts/pin_deps.sh"
        )

    def test_hash_file_has_pinned_versions(self):
        """
        Every non-comment, non-continuation, non-blank line that names a
        package should use == (pinned) not >= (range).
        """
        content = REQUIREMENTS_HASH.read_text()
        range_pkgs = []
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("-") or stripped.startswith("\\"):
                continue
            # Package lines look like:  some-package==1.2.3 \
            if ">=" in stripped and "==" not in stripped:
                range_pkgs.append(stripped)
        assert range_pkgs == [], (
            f"requirements.hash.txt contains unpinned entries: {range_pkgs}; "
            "regenerate with: scripts/pin_deps.sh"
        )

    def test_hash_file_covers_fastapi(self):
        """fastapi must be included as it is a security-critical package."""
        content = REQUIREMENTS_HASH.read_text()
        assert "fastapi==" in content.lower() or "fastapi ==" in content.lower(), (
            "fastapi not found in requirements.hash.txt"
        )

    def test_hash_file_covers_cryptography(self):
        content = REQUIREMENTS_HASH.read_text()
        assert "cryptography==" in content.lower(), (
            "cryptography not found in requirements.hash.txt"
        )


# ===========================================================================
# 2. requirements.in
# ===========================================================================


class TestRequirementsIn:
    def test_requirements_in_present(self):
        assert REQUIREMENTS_IN.exists(), "requirements.in is missing"

    def test_requirements_in_references_fastapi(self):
        content = REQUIREMENTS_IN.read_text().lower()
        assert "fastapi" in content

    def test_requirements_in_references_cryptography(self):
        content = REQUIREMENTS_IN.read_text().lower()
        assert "cryptography" in content

    def test_requirements_in_no_pinned_versions(self):
        """
        requirements.in should use >= constraints, not == pins.
        Exact pins belong in requirements.hash.txt.
        """
        content = REQUIREMENTS_IN.read_text()
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            assert "==" not in stripped, (
                f"requirements.in should use >= ranges, not ==: '{stripped}'"
            )


# ===========================================================================
# 3. scripts/pin_deps.sh
# ===========================================================================


class TestPinDepsScript:
    def test_pin_deps_sh_exists(self):
        assert PIN_DEPS_SH.exists(), "scripts/pin_deps.sh is missing"

    def test_pin_deps_sh_executable(self):
        assert os.access(PIN_DEPS_SH, os.X_OK), (
            "scripts/pin_deps.sh is not executable — run: chmod +x scripts/pin_deps.sh"
        )

    def test_pin_deps_sh_help(self):
        """--help flag should exit 0 and print usage."""
        result = subprocess.run(
            [str(PIN_DEPS_SH), "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"--help returned non-zero: {result.stderr}"

    def test_pin_deps_sh_unknown_flag_fails(self):
        result = subprocess.run(
            [str(PIN_DEPS_SH), "--unknown-flag"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0


# ===========================================================================
# 4. gen_node_security_report.py — discover_nodes
# ===========================================================================


class TestDiscoverNodes:
    def test_discovers_at_least_one_node(self):
        mod = _import_gen_report()
        nodes = mod.discover_nodes()
        assert len(nodes) > 0, "No nodes discovered"

    def test_discovered_nodes_start_with_node_prefix(self):
        mod = _import_gen_report()
        nodes = mod.discover_nodes()
        for n in nodes:
            assert n.startswith("Node_"), f"Unexpected node name: {n}"

    def test_discovered_nodes_are_sorted(self):
        mod = _import_gen_report()
        nodes = mod.discover_nodes()
        assert nodes == sorted(nodes), "discover_nodes() should return sorted list"

    def test_discover_nodes_returns_only_dirs_with_main_py(self, tmp_path):
        """Directories without main.py should be excluded."""
        mod = _import_gen_report()
        # Create a fake node dir without main.py
        (tmp_path / "Node_99_Fake").mkdir()
        (tmp_path / "Node_00_Real").mkdir()
        (tmp_path / "Node_00_Real" / "main.py").write_text("")
        nodes = mod.discover_nodes(tmp_path)
        assert "Node_00_Real" in nodes
        assert "Node_99_Fake" not in nodes


# ===========================================================================
# 5. gen_node_security_report.py — build_node_report
# ===========================================================================


class TestBuildNodeReport:
    def _first_node(self):
        mod = _import_gen_report()
        nodes = mod.discover_nodes()
        assert nodes, "No nodes available for testing"
        return nodes[0], mod

    def test_report_has_required_schema_keys(self):
        node_name, mod = self._first_node()
        report = mod.build_node_report(
            node_name, check_signatures=False
        )
        required_keys = [
            "schema_version", "generated_at", "node", "image",
            "sbom", "signature", "dependencies", "hash_locked",
            "supply_chain_checks",
        ]
        for key in required_keys:
            assert key in report, f"Missing key in report: {key}"

    def test_report_node_name_matches(self):
        node_name, mod = self._first_node()
        report = mod.build_node_report(node_name, check_signatures=False)
        assert report["node"] == node_name

    def test_report_hash_locked_true_when_file_present(self):
        node_name, mod = self._first_node()
        report = mod.build_node_report(node_name, check_signatures=False)
        assert report["hash_locked"] is True, (
            "requirements.hash.txt not found — report should reflect hash_locked=True"
        )

    def test_report_supply_chain_checks_structure(self):
        node_name, mod = self._first_node()
        report = mod.build_node_report(node_name, check_signatures=False)
        checks = report["supply_chain_checks"]
        assert "sbom_present" in checks
        assert "signature_verified" in checks
        assert "hash_locked_deps" in checks

    def test_report_image_ref_format(self):
        node_name, mod = self._first_node()
        report = mod.build_node_report(
            node_name,
            image_prefix="ghcr.io/org/",
            tag="v1.0",
            check_signatures=False,
        )
        assert report["image"]["ref"].startswith("ghcr.io/org/")
        assert report["image"]["ref"].endswith(":v1.0")

    def test_report_sig_skipped_when_not_checking(self):
        node_name, mod = self._first_node()
        report = mod.build_node_report(node_name, check_signatures=False)
        assert report["signature"]["method"] == "skipped"

    def test_report_sbom_absent_when_no_sbom_dir(self):
        node_name, mod = self._first_node()
        report = mod.build_node_report(
            node_name, sbom_dir=None, check_signatures=False
        )
        assert report["sbom"]["present"] is False

    def test_report_sbom_found_when_file_present(self, tmp_path):
        mod = _import_gen_report()
        nodes = mod.discover_nodes()
        node_name = nodes[0]
        # Create a fake CycloneDX SBOM file named after the node
        sbom_data = {"components": [{"name": "pkg-a"}, {"name": "pkg-b"}]}
        sbom_file = tmp_path / f"{node_name.lower()}.sbom.json"
        sbom_file.write_text(json.dumps(sbom_data))
        report = mod.build_node_report(
            node_name, sbom_dir=tmp_path, check_signatures=False
        )
        assert report["sbom"]["present"] is True
        assert report["sbom"]["component_count"] == 2
        assert report["supply_chain_checks"]["sbom_present"] is True


# ===========================================================================
# 6. main() CLI — combined summary
# ===========================================================================


class TestGenReportCLI:
    def test_list_nodes_flag(self):
        result = subprocess.run(
            [sys.executable, str(GEN_REPORT_PY), "--list-nodes"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Node_" in result.stdout

    def test_generates_summary_json(self, tmp_path):
        mod = _import_gen_report()
        nodes = mod.discover_nodes()
        # Run for just the first 3 nodes to keep the test fast
        sample = nodes[:3]
        ret = mod.main(
            [
                "--nodes", *sample,
                "--no-sig-check",
                "--output-dir", str(tmp_path),
            ]
        )
        assert ret == 0
        summary_file = tmp_path / "security-summary.json"
        assert summary_file.exists()
        summary = json.loads(summary_file.read_text())
        assert summary["total_nodes"] == len(sample)

    def test_summary_required_fields(self, tmp_path):
        mod = _import_gen_report()
        nodes = mod.discover_nodes()
        mod.main(
            [
                "--nodes", nodes[0],
                "--no-sig-check",
                "--output-dir", str(tmp_path),
            ]
        )
        summary = json.loads((tmp_path / "security-summary.json").read_text())
        required = [
            "schema_version", "generated_at", "total_nodes",
            "nodes_with_sbom", "nodes_with_verified_signature",
            "nodes_with_hash_locked_deps", "nodes",
        ]
        for field in required:
            assert field in summary, f"Missing field in summary: {field}"

    def test_per_node_json_files_generated(self, tmp_path):
        mod = _import_gen_report()
        nodes = mod.discover_nodes()
        sample = nodes[:2]
        mod.main(
            [
                "--nodes", *sample,
                "--no-sig-check",
                "--output-dir", str(tmp_path),
            ]
        )
        for node in sample:
            assert (tmp_path / f"{node}.security.json").exists(), (
                f"Per-node JSON not generated for {node}"
            )

    def test_text_format_output(self, tmp_path):
        mod = _import_gen_report()
        nodes = mod.discover_nodes()
        mod.main(
            [
                "--nodes", nodes[0],
                "--no-sig-check",
                "--format", "text",
                "--output-dir", str(tmp_path),
            ]
        )
        txt = tmp_path / f"{nodes[0]}.security.txt"
        assert txt.exists()
        content = txt.read_text()
        assert "Node:" in content
        assert "SBOM:" in content
        assert "Signature:" in content

    def test_summary_only_skips_per_node_files(self, tmp_path):
        mod = _import_gen_report()
        nodes = mod.discover_nodes()
        sample = nodes[:2]
        mod.main(
            [
                "--nodes", *sample,
                "--no-sig-check",
                "--summary-only",
                "--output-dir", str(tmp_path),
            ]
        )
        # Summary must exist
        assert (tmp_path / "security-summary.json").exists()
        # Per-node files must NOT exist
        for node in sample:
            assert not (tmp_path / f"{node}.security.json").exists()

    def test_nonexistent_node_is_warned_but_continues(self, tmp_path, capsys):
        mod = _import_gen_report()
        nodes = mod.discover_nodes()
        ret = mod.main(
            [
                "--nodes", nodes[0], "Node_DOES_NOT_EXIST_99999",
                "--no-sig-check",
                "--output-dir", str(tmp_path),
            ]
        )
        assert ret == 0
        captured = capsys.readouterr()
        assert "Warning" in captured.err or "not found" in captured.err.lower()


# ===========================================================================
# 7. pip --require-hashes smoke test
# ===========================================================================


class TestPipHashVerify:
    """Verify that pip can install the committed requirements.hash.txt."""

    @pytest.mark.slow
    def test_pip_require_hashes_dry_run(self):
        """
        Run pip install --require-hashes --dry-run to validate the hash file
        without actually downloading / installing packages.
        """
        result = subprocess.run(
            [
                sys.executable, "-m", "pip", "install",
                "--require-hashes",
                "--dry-run",
                "-r", str(REQUIREMENTS_HASH),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"pip --require-hashes --dry-run failed:\n{result.stderr}"
        )
