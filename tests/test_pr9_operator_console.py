#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr9_operator_console.py
====================================
PR-9 — Unified Visual Operator / Ecosystem Console.

Validates:
  1.  static/operator-console/index.html exists.
  2.  The console HTML references all required OPERATOR_ROUTES_V1 API paths.
  3.  The console HTML does NOT define its own data-model objects (no parallel
      truth source).
  4.  All operator API endpoints remain accessible and return JSON backed by
      OPERATOR_ROUTES_V1 (data-binding integration tests).
  5.  The unified_launcher.py registers the /operator-console route.
  6.  No second backend aggregation route is introduced alongside the console.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _console_html() -> str:
    p = PROJECT_ROOT / "static" / "operator-console" / "index.html"
    return p.read_text(encoding="utf-8")


def _launcher_text() -> str:
    return (PROJECT_ROOT / "unified_launcher.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def op_app():
    from core.routes.operator import create_router
    from core.android_device_state_store import reset_android_device_state_store
    reset_android_device_state_store()
    app = FastAPI()
    app.include_router(create_router())
    return app


@pytest.fixture(scope="module")
def op_client(op_app):
    return TestClient(op_app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# 1.  Static file presence
# ---------------------------------------------------------------------------

class TestStaticFilePresence:
    def test_console_html_exists(self):
        p = PROJECT_ROOT / "static" / "operator-console" / "index.html"
        assert p.exists(), f"Missing: {p}"

    def test_console_html_not_empty(self):
        assert len(_console_html()) > 1000

    def test_console_html_is_valid_html(self):
        html = _console_html()
        assert "<!doctype html>" in html.lower()


# ---------------------------------------------------------------------------
# 2.  API path references in the console
# ---------------------------------------------------------------------------

REQUIRED_API_PATHS = [
    "/api/v1/readiness",
    "/api/v1/operator/snapshot",
    "/api/v1/operator/flows",
    "/api/v1/operator/llm",
    "/api/v1/operator/nats",
    "/api/v1/operator/heartbeat",
    "/api/v1/ports",
    "/api/v1/operator/devices/ecosystem",
    "/api/v1/operator/devices/execution-events",
]


class TestApiPathReferences:
    @pytest.mark.parametrize("api_path", REQUIRED_API_PATHS)
    def test_console_references_api_path(self, api_path):
        html = _console_html()
        assert api_path in html, (
            f"Operator console HTML does not reference API path: {api_path}"
        )

    def test_all_paths_reference_operator_routes_v1_authority(self):
        html = _console_html()
        assert "OPERATOR_ROUTES_V1" in html


# ---------------------------------------------------------------------------
# 3.  No parallel truth model in the console
# ---------------------------------------------------------------------------

class TestNoParallelTruthModel:
    def test_console_does_not_define_device_class(self):
        html = _console_html()
        # A real Device class definition would be 'class Device {' or 'class Device{'
        assert "class Device {" not in html
        assert "class Device{" not in html

    def test_console_does_not_define_flow_state_store(self):
        html = _console_html()
        assert "FlowStateStore" not in html
        assert "DeviceStateStore" not in html

    def test_console_fetches_from_api(self):
        html = _console_html()
        # Must use fetch() to call real APIs
        assert "fetch(" in html or "apiFetch(" in html

    def test_console_has_no_hardcoded_mock_devices(self):
        html = _console_html()
        # Should not have hardcoded mock device arrays
        assert "mock_device" not in html.lower()


# ---------------------------------------------------------------------------
# 4.  Data-binding — operator API endpoints return correct payload shapes
# ---------------------------------------------------------------------------

class TestReadinessBinding:
    def test_readiness_returns_200(self, op_client):
        r = op_client.get("/api/v1/readiness")
        assert r.status_code == 200

    def test_readiness_has_verdict(self, op_client):
        data = op_client.get("/api/v1/readiness").json()
        assert "verdict" in data

    def test_readiness_has_dimensions_list(self, op_client):
        data = op_client.get("/api/v1/readiness").json()
        assert "dimensions" in data
        assert isinstance(data["dimensions"], list)


class TestSnapshotBinding:
    def test_snapshot_returns_200(self, op_client):
        r = op_client.get("/api/v1/operator/snapshot")
        assert r.status_code == 200

    def test_snapshot_has_authority(self, op_client):
        data = op_client.get("/api/v1/operator/snapshot").json()
        # The snapshot endpoint carries OPERATOR_SURFACE_V1 (from the
        # OperatorSurface layer) or OPERATOR_ROUTES_V1 — either is valid.
        auth = data.get("authority", "")
        assert "OPERATOR" in auth, f"Expected an OPERATOR authority, got: {auth!r}"


class TestFlowsBinding:
    def test_flows_returns_200(self, op_client):
        r = op_client.get("/api/v1/operator/flows")
        assert r.status_code == 200

    def test_flows_has_flows_list(self, op_client):
        data = op_client.get("/api/v1/operator/flows").json()
        assert "flows" in data
        assert isinstance(data["flows"], list)

    def test_flows_has_authority(self, op_client):
        data = op_client.get("/api/v1/operator/flows").json()
        assert data.get("authority") == "OPERATOR_ROUTES_V1"


class TestNatsBinding:
    def test_nats_returns_200(self, op_client):
        r = op_client.get("/api/v1/operator/nats")
        assert r.status_code == 200

    def test_nats_has_connected_key(self, op_client):
        data = op_client.get("/api/v1/operator/nats").json()
        assert "connected" in data


class TestHeartbeatBinding:
    def test_heartbeat_returns_200(self, op_client):
        r = op_client.get("/api/v1/operator/heartbeat")
        assert r.status_code == 200

    def test_heartbeat_has_enabled_key(self, op_client):
        data = op_client.get("/api/v1/operator/heartbeat").json()
        assert "enabled" in data


class TestPortsBinding:
    def test_ports_returns_200(self, op_client):
        r = op_client.get("/api/v1/ports")
        assert r.status_code == 200

    def test_ports_returns_object(self, op_client):
        data = op_client.get("/api/v1/ports").json()
        assert isinstance(data, dict)


class TestEcosystemBinding:
    def test_ecosystem_returns_200(self, op_client):
        r = op_client.get("/api/v1/operator/devices/ecosystem")
        assert r.status_code == 200

    def test_ecosystem_has_authority(self, op_client):
        data = op_client.get("/api/v1/operator/devices/ecosystem").json()
        assert data.get("authority") == "OPERATOR_ROUTES_V1"


class TestExecutionEventsBinding:
    def test_execution_events_returns_200(self, op_client):
        r = op_client.get("/api/v1/operator/devices/execution-events")
        assert r.status_code == 200

    def test_execution_events_has_events_list(self, op_client):
        data = op_client.get("/api/v1/operator/devices/execution-events").json()
        assert "events" in data
        assert isinstance(data["events"], list)

    def test_execution_events_has_authority(self, op_client):
        data = op_client.get("/api/v1/operator/devices/execution-events").json()
        assert data.get("authority") == "OPERATOR_ROUTES_V1"

    def test_execution_events_has_diagnostics_source_fingerprint(self, op_client):
        data = op_client.get("/api/v1/operator/devices/execution-events").json()
        fp = data.get("authority_source_fingerprint")
        assert isinstance(fp, dict)
        assert fp.get("surface_path") == "/api/v1/operator/devices/execution-events"
        assert fp.get("primary_source_kind") == "diagnostics_visible_state"
        assert fp.get("primary_source_kind") != "canonical_truth"


# ---------------------------------------------------------------------------
# 5.  unified_launcher.py registers /operator-console
# ---------------------------------------------------------------------------

class TestLauncherRoute:
    def test_launcher_has_operator_console_route(self):
        text = _launcher_text()
        assert "/operator-console" in text

    def test_launcher_references_operator_console_dir(self):
        text = _launcher_text()
        assert "operator-console" in text

    def test_launcher_uses_file_response_for_console(self):
        text = _launcher_text()
        assert "operator_console_index" in text


# ---------------------------------------------------------------------------
# 6.  No new backend aggregation route introduced
# ---------------------------------------------------------------------------

class TestNoSecondAggregationLayer:
    def test_operator_console_route_not_in_operator_py(self):
        op_py = (PROJECT_ROOT / "core" / "routes" / "operator.py").read_text()
        # The operator-console HTML route should live in the launcher, not in
        # operator.py (which is the API truth surface, not a UI server).
        assert "/operator-console" not in op_py

    def test_no_aggregation_route_added_to_operator_py(self):
        op_py = (PROJECT_ROOT / "core" / "routes" / "operator.py").read_text()
        # Guard against accidental addition of an aggregation endpoint that
        # merges multiple truth sources outside the canonical operator surface.
        assert "aggregate_all" not in op_py
        assert "/api/v1/operator/console" not in op_py
