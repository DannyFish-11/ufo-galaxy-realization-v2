#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_batch_pr4_api_route_decomposition.py
================================================
Batch PR-4 — Canonical API route decomposition and dashboard demotion.

Validates:
  1.  core/routes/health.py exists.
  2.  core/routes/health.py defines HEALTH_ROUTES_AUTHORITY sentinel.
  3.  core/routes/health.py has create_router() callable.
  4.  GET /api/v1/health/unified is served by health domain module.
  5.  GET /api/v1/health/quick is served by health domain module.
  6.  core/routes/diagnostics.py exists.
  7.  core/routes/diagnostics.py defines DIAGNOSTICS_ROUTES_AUTHORITY sentinel.
  8.  core/routes/diagnostics.py has create_router() callable.
  9.  GET /api/v1/concurrency/status is served by diagnostics domain module.
 10.  GET /api/v1/errors/summary is served by diagnostics domain module.
 11.  GET /api/v1/discovery/status is served by diagnostics domain module.
 12.  GET /api/v1/security/audit is served by diagnostics domain module.
 13.  GET /api/v1/security/stats is served by diagnostics domain module.
 14.  GET /api/v1/config/status is served by diagnostics domain module.
 15.  GET /api/v1/config/versions is served by diagnostics domain module.
 16.  core/api_routes.py defines CANONICAL_API_ROUTES_AUTHORITY sentinel.
 17.  CANONICAL_API_ROUTES_AUTHORITY == "core.api_routes".
 18.  core/api_routes.py create_api_routes() includes health routes.
 19.  core/api_routes.py create_api_routes() includes diagnostics routes.
 20.  dashboard/backend/main.py defines DASHBOARD_LEGACY_SURFACE_AUTHORITY sentinel.
 21.  DASHBOARD_LEGACY_SURFACE_AUTHORITY contains 'LEGACY_SURFACE'.
 22.  dashboard/backend/main.py docstring contains 'LEGACY UI SURFACE'.
 23.  core/routes/monitoring.py no longer defines /api/v1/health/unified route.
 24.  core/routes/monitoring.py no longer defines /api/v1/concurrency/status route.
 25.  core/routes/__init__.py documents health.py module.
 26.  core/routes/__init__.py documents diagnostics.py module.
 27.  CANONICAL_ENTRYPOINTS.md documents health.py module.
 28.  CANONICAL_ENTRYPOINTS.md documents diagnostics.py module.
 29.  Canonical API exposes /api/v1/health/unified via aggregated router.
 30.  Canonical API exposes /api/v1/concurrency/status via aggregated router.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
import unittest

# ── project root ─────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent


# ── helpers ──────────────────────────────────────────────────────────────────

def _read(rel_path: str) -> str:
    return (PROJECT_ROOT / rel_path).read_text(encoding="utf-8")


def _exists(rel_path: str) -> bool:
    return (PROJECT_ROOT / rel_path).exists()


def _import_fresh(module_path: str):
    if module_path in sys.modules:
        del sys.modules[module_path]
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    return importlib.import_module(module_path)


# ── test class ───────────────────────────────────────────────────────────────


class TestBatchPR4APIRouteDecomposition(unittest.TestCase):
    """Batch PR-4 — canonical API route decomposition and dashboard demotion."""

    # ------------------------------------------------------------------
    # Group 1: health.py domain module
    # ------------------------------------------------------------------

    def test_01_health_module_exists(self):
        self.assertTrue(_exists("core/routes/health.py"),
                        "core/routes/health.py must exist")

    def test_02_health_module_has_authority_sentinel(self):
        content = _read("core/routes/health.py")
        self.assertIn("HEALTH_ROUTES_AUTHORITY", content,
                      "health.py must define HEALTH_ROUTES_AUTHORITY sentinel")

    def test_03_health_module_has_create_router(self):
        content = _read("core/routes/health.py")
        self.assertIn("def create_router", content,
                      "health.py must define create_router()")

    def test_04_health_module_has_unified_route(self):
        content = _read("core/routes/health.py")
        self.assertIn("/api/v1/health/unified", content,
                      "health.py must define /api/v1/health/unified route")

    def test_05_health_module_has_quick_route(self):
        content = _read("core/routes/health.py")
        self.assertIn("/api/v1/health/quick", content,
                      "health.py must define /api/v1/health/quick route")

    # ------------------------------------------------------------------
    # Group 2: diagnostics.py domain module
    # ------------------------------------------------------------------

    def test_06_diagnostics_module_exists(self):
        self.assertTrue(_exists("core/routes/diagnostics.py"),
                        "core/routes/diagnostics.py must exist")

    def test_07_diagnostics_module_has_authority_sentinel(self):
        content = _read("core/routes/diagnostics.py")
        self.assertIn("DIAGNOSTICS_ROUTES_AUTHORITY", content,
                      "diagnostics.py must define DIAGNOSTICS_ROUTES_AUTHORITY sentinel")

    def test_08_diagnostics_module_has_create_router(self):
        content = _read("core/routes/diagnostics.py")
        self.assertIn("def create_router", content,
                      "diagnostics.py must define create_router()")

    def test_09_diagnostics_has_concurrency_route(self):
        content = _read("core/routes/diagnostics.py")
        self.assertIn("/api/v1/concurrency/status", content)

    def test_10_diagnostics_has_errors_route(self):
        content = _read("core/routes/diagnostics.py")
        self.assertIn("/api/v1/errors/summary", content)

    def test_11_diagnostics_has_discovery_route(self):
        content = _read("core/routes/diagnostics.py")
        self.assertIn("/api/v1/discovery/status", content)

    def test_12_diagnostics_has_security_audit_route(self):
        content = _read("core/routes/diagnostics.py")
        self.assertIn("/api/v1/security/audit", content)

    def test_13_diagnostics_has_security_stats_route(self):
        content = _read("core/routes/diagnostics.py")
        self.assertIn("/api/v1/security/stats", content)

    def test_14_diagnostics_has_config_status_route(self):
        content = _read("core/routes/diagnostics.py")
        self.assertIn("/api/v1/config/status", content)

    def test_15_diagnostics_has_config_versions_route(self):
        content = _read("core/routes/diagnostics.py")
        self.assertIn("/api/v1/config/versions", content)

    # ------------------------------------------------------------------
    # Group 3: canonical api_routes.py authority
    # ------------------------------------------------------------------

    def test_16_api_routes_has_canonical_authority_sentinel(self):
        content = _read("core/api_routes.py")
        self.assertIn("CANONICAL_API_ROUTES_AUTHORITY", content,
                      "core/api_routes.py must define CANONICAL_API_ROUTES_AUTHORITY")

    def test_17_canonical_authority_value(self):
        content = _read("core/api_routes.py")
        self.assertIn('CANONICAL_API_ROUTES_AUTHORITY = "core.api_routes"', content,
                      "CANONICAL_API_ROUTES_AUTHORITY must equal 'core.api_routes'")

    def test_18_api_routes_includes_health_module(self):
        content = _read("core/api_routes.py")
        self.assertIn("health_routes", content,
                      "create_api_routes() must include health_routes sub-module")

    def test_19_api_routes_includes_diagnostics_module(self):
        content = _read("core/api_routes.py")
        self.assertIn("diagnostics_routes", content,
                      "create_api_routes() must include diagnostics_routes sub-module")

    # ------------------------------------------------------------------
    # Group 4: dashboard demotion
    # ------------------------------------------------------------------

    def test_20_dashboard_has_legacy_authority_sentinel(self):
        content = _read("dashboard/backend/main.py")
        self.assertIn("DASHBOARD_LEGACY_SURFACE_AUTHORITY", content,
                      "dashboard/backend/main.py must define DASHBOARD_LEGACY_SURFACE_AUTHORITY")

    def test_21_dashboard_legacy_sentinel_contains_legacy_surface(self):
        content = _read("dashboard/backend/main.py")
        self.assertIn("LEGACY_SURFACE", content,
                      "DASHBOARD_LEGACY_SURFACE_AUTHORITY must contain 'LEGACY_SURFACE'")

    def test_22_dashboard_docstring_contains_legacy_marker(self):
        content = _read("dashboard/backend/main.py")
        self.assertIn("LEGACY UI SURFACE", content,
                      "dashboard/backend/main.py docstring must contain 'LEGACY UI SURFACE'")

    # ------------------------------------------------------------------
    # Group 5: monitoring.py does NOT own health/diagnostics routes
    # ------------------------------------------------------------------

    def test_23_monitoring_does_not_own_health_unified(self):
        content = _read("core/routes/monitoring.py")
        self.assertNotIn('/api/v1/health/unified"', content,
                         "monitoring.py must not define /api/v1/health/unified (moved to health.py)")

    def test_24_monitoring_does_not_own_concurrency(self):
        content = _read("core/routes/monitoring.py")
        self.assertNotIn('/api/v1/concurrency/status"', content,
                         "monitoring.py must not define /api/v1/concurrency/status (moved to diagnostics.py)")

    # ------------------------------------------------------------------
    # Group 6: routes/__init__.py documents new modules
    # ------------------------------------------------------------------

    def test_25_routes_init_documents_health(self):
        content = _read("core/routes/__init__.py")
        self.assertIn("health.py", content,
                      "core/routes/__init__.py must document health.py module")

    def test_26_routes_init_documents_diagnostics(self):
        content = _read("core/routes/__init__.py")
        self.assertIn("diagnostics.py", content,
                      "core/routes/__init__.py must document diagnostics.py module")

    # ------------------------------------------------------------------
    # Group 7: architecture docs
    # ------------------------------------------------------------------

    def test_27_canonical_entrypoints_documents_health_module(self):
        content = _read("docs/architecture/CANONICAL_ENTRYPOINTS.md")
        self.assertIn("health.py", content,
                      "CANONICAL_ENTRYPOINTS.md must reference health.py")

    def test_28_canonical_entrypoints_documents_diagnostics_module(self):
        content = _read("docs/architecture/CANONICAL_ENTRYPOINTS.md")
        self.assertIn("diagnostics.py", content,
                      "CANONICAL_ENTRYPOINTS.md must reference diagnostics.py")

    # ------------------------------------------------------------------
    # Group 8: functional validation — aggregated router exposes routes
    # ------------------------------------------------------------------

    def test_29_aggregated_router_serves_health_route(self):
        """create_api_routes() must include /api/v1/health/unified."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from core.api_routes import create_api_routes

        app = FastAPI()
        router = create_api_routes()
        app.include_router(router)
        client = TestClient(app)

        # The route should exist (200 or 5xx is fine — we test route registration)
        paths = [r.path for r in app.routes]
        self.assertIn("/api/v1/health/unified", paths,
                      "/api/v1/health/unified must be registered in aggregated router")

    def test_30_aggregated_router_serves_diagnostics_route(self):
        """create_api_routes() must include /api/v1/concurrency/status."""
        from fastapi import FastAPI
        from core.api_routes import create_api_routes

        app = FastAPI()
        router = create_api_routes()
        app.include_router(router)

        paths = [r.path for r in app.routes]
        self.assertIn("/api/v1/concurrency/status", paths,
                      "/api/v1/concurrency/status must be registered in aggregated router")


if __name__ == "__main__":
    unittest.main()
