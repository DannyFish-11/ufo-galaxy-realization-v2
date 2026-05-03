#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import runpy
import subprocess
import sys
from pathlib import Path

from tools.architecture.architecture_completion import get_architecture_completion_scorecard
from tools.architecture.architecture_live_status import get_architecture_live_status


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_mainline_reality_report.py"


def _load_module():
    return runpy.run_path(str(SCRIPT_PATH))


def _build_report():
    module = _load_module()
    return module["build_mainline_reality_report"](REPO_ROOT)


def test_report_tracks_authoritative_scorecard_and_live_status():
    report = _build_report()
    scorecard = get_architecture_completion_scorecard(force_rebuild=True)
    live_status = get_architecture_live_status(force_rebuild=True)

    assert report.completion_pct == scorecard.overall_completion_pct
    assert report.runtime_readiness == live_status.runtime_readiness
    assert report.canonical_dimension_count == scorecard.canonical_count
    assert report.total_dimensions == scorecard.total_dimensions
    assert report.legacy_ambiguity_dimensions == [
        dimension.dimension.value for dimension in scorecard.legacy_ambiguity_dimensions()
    ]


def test_report_describes_canonical_mainline_chain_and_projection_surfaces():
    report = _build_report()

    assert report.startup_entrypoint == "main.py → unified_launcher.py"
    assert report.canonical_runtime_chain[:3] == [
        "main.py",
        "unified_launcher.py",
        "core.desktop_presence_runtime",
    ]
    assert "core.openclawd" in report.canonical_runtime_chain
    assert "GET /api/v1/projection/runtime" in report.projection_surfaces
    assert "windows_client.status_board_v2" in report.projection_surfaces


def test_report_node_count_matches_real_node_directory_count():
    report = _build_report()
    expected = sum(
        1
        for path in (REPO_ROOT / "nodes").iterdir()
        if path.is_dir() and path.name.startswith("Node_")
    )
    assert report.node_count == expected


def test_text_rendering_exposes_completion_and_closure():
    report = _build_report()
    render_text_report = _load_module()["render_text_report"]
    text = render_text_report(report)

    assert "Galaxy 主链真实现状" in text
    assert f"{report.completion_pct:.1f}%" in text
    assert report.runtime_readiness in text
    assert "当前无主链阻塞或遗留模糊维度" in text
    assert "当前遗留模糊维度：无" in text
    assert "当前未发现需要特别提示的遗留表层" in text
    assert report.completion_pct == 100.0
    assert report.runtime_readiness == "ready"
    assert report.canonical_dimension_count == report.total_dimensions
    assert report.main_blockers == []
    assert report.active_legacy_surfaces == []


def test_cli_json_output_is_machine_readable():
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--json"],
        check=True,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    payload = json.loads(result.stdout)
    assert payload["startup_entrypoint"] == "main.py → unified_launcher.py"
    assert payload["completion_pct"] >= 0.0
    assert payload["runtime_readiness"] in {"ready", "partial", "blocked"}
