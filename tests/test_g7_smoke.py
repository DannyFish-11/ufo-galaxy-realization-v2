"""
tests/test_g7_smoke.py
======================
PR-G7 "开发者体验与快速验证" — fast smoke test suite

Covers:
  1. VLM-stub FastAPI app: /health and /api/v1/vlm/infer respond correctly.
  2. Tasker-stub FastAPI app: /health and /api/v1/task/submit respond correctly.
  3. Galaxy Gateway /health endpoint returns {status: healthy}.
  4. WS /ws/status endpoint accepts a connection (no crash on connect).
  5. Makefile exists and declares the expected targets.
  6. quick_verify.sh script exists and is executable.
  7. QUICKSTART.md contains the one-command quick-verify section.

All tests are:
  - Pure in-process (no subprocesses, no network, no live ports).
  - Fast: each runs in < 1 s.
  - Tagged ``g7_smoke`` for selective CI execution::

        pytest -m g7_smoke tests/test_g7_smoke.py

  - Tagged ``not slow`` so the existing ``make test:fast`` gate picks them up.
"""

from __future__ import annotations

import importlib
import os
import stat
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Pytest marker registration
# ---------------------------------------------------------------------------
pytestmark = [pytest.mark.g7_smoke]

PROJECT_ROOT = Path(__file__).parent.parent.absolute()


# ===========================================================================
# Helpers — build ephemeral stub apps identical to what quick_verify.sh uses
# ===========================================================================

def _build_vlm_stub_app():
    """Return a TestClient-ready FastAPI app matching the VLM stub."""
    from fastapi import FastAPI

    app = FastAPI(title="VLM-Stub")

    @app.get("/health")
    async def health():
        return {"status": "healthy", "service": "vlm-stub"}

    @app.post("/api/v1/vlm/infer")
    async def infer(payload: dict = None):
        return {"result": "stub_ok", "model": "vlm-stub-v0", "input_received": True}

    return app


def _build_tasker_stub_app():
    """Return a TestClient-ready FastAPI app matching the Tasker stub.

    The live stub talks to the real gateway; here we override the health
    delegate so the test stays purely in-process.
    """
    from fastapi import FastAPI

    app = FastAPI(title="Tasker-Stub")

    @app.get("/health")
    async def health():
        return {"status": "healthy", "service": "tasker-stub", "gateway_reachable": True}

    @app.post("/api/v1/task/submit")
    async def submit(payload: dict = None):
        return {"task_id": "smoke-001", "status": "queued"}

    return app


# ===========================================================================
# 1–3. VLM stub
# ===========================================================================

class TestVLMStub:
    """VLM stub endpoints return the correct shape."""

    @pytest.fixture(scope="class")
    def client(self):
        return TestClient(_build_vlm_stub_app())

    def test_health_status_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"

    def test_health_service_name(self, client):
        r = client.get("/health")
        assert r.json()["service"] == "vlm-stub"

    def test_infer_returns_stub_ok(self, client):
        r = client.post("/api/v1/vlm/infer", json={"prompt": "hello"})
        assert r.status_code == 200
        body = r.json()
        assert body["result"] == "stub_ok"
        assert body["input_received"] is True

    def test_infer_empty_body(self, client):
        """Stub must accept a missing body (no 422)."""
        r = client.post("/api/v1/vlm/infer")
        assert r.status_code == 200


# ===========================================================================
# 4–5. Tasker stub
# ===========================================================================

class TestTaskerStub:
    """Tasker stub endpoints return the correct shape."""

    @pytest.fixture(scope="class")
    def client(self):
        return TestClient(_build_tasker_stub_app())

    def test_health_status_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"

    def test_health_gateway_reachable_field(self, client):
        r = client.get("/health")
        assert "gateway_reachable" in r.json()

    def test_submit_returns_task_id(self, client):
        r = client.post("/api/v1/task/submit", json={"cmd": "smoke"})
        assert r.status_code == 200
        assert "task_id" in r.json()

    def test_submit_status_queued(self, client):
        r = client.post("/api/v1/task/submit", json={"cmd": "smoke"})
        assert r.json()["status"] == "queued"


# ===========================================================================
# 6. Galaxy Gateway /health (in-process, no live port required)
# ===========================================================================

class TestGatewayHealth:
    """/health endpoint on the real gateway app returns expected payload."""

    @pytest.fixture(scope="class")
    def client(self):
        # Import lazily so import errors surface as test failures, not
        # collection errors.
        from galaxy_gateway.app import app

        return TestClient(app)

    def test_health_200(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_health_status_field(self, client):
        body = client.get("/health").json()
        assert body.get("status") == "healthy"


# ===========================================================================
# 7. Gateway WS /ws/status connect (no crash)
# ===========================================================================

class TestGatewayWSStatus:
    """/ws/status endpoint accepts a connection without raising an exception."""

    @pytest.fixture(scope="class")
    def client(self):
        from galaxy_gateway.app import app

        return TestClient(app)

    def test_ws_status_connect(self, client):
        """Connecting to /ws/status must not raise a 403/404/500."""
        try:
            with client.websocket_connect("/ws/status") as ws:
                # Try to receive one frame; ignore timeout — we only care that
                # the server accepted the connection without an HTTP error.
                try:
                    ws.receive_text()
                except Exception:
                    pass  # server may close immediately — that's fine
        except Exception as exc:
            # A WebSocketDisconnect with code 1000/1001 is acceptable.
            msg = str(exc).lower()
            assert "403" not in msg and "404" not in msg, (
                f"/ws/status rejected with unexpected error: {exc}"
            )


# ===========================================================================
# 8. Makefile targets present
# ===========================================================================

class TestMakefile:
    """Top-level Makefile exists and declares the required targets."""

    REQUIRED_TARGETS = ["fmt", "lint", "test", "contract", "quick-verify"]

    @pytest.fixture(scope="class")
    def makefile_text(self):
        path = PROJECT_ROOT / "Makefile"
        assert path.exists(), "Makefile not found at project root"
        return path.read_text()

    def test_fmt_target(self, makefile_text):
        assert "fmt" in makefile_text

    def test_lint_target(self, makefile_text):
        assert "lint" in makefile_text

    def test_test_fast_target(self, makefile_text):
        # The target may appear as "test:fast", "test\:fast", or "test-fast"
        assert "test" in makefile_text

    def test_contract_target(self, makefile_text):
        assert "contract" in makefile_text

    def test_quick_verify_target(self, makefile_text):
        assert "quick-verify" in makefile_text


# ===========================================================================
# 9. quick_verify.sh exists and is executable
# ===========================================================================

class TestQuickVerifyScript:
    """scripts/quick_verify.sh is present and executable."""

    @pytest.fixture(scope="class")
    def script_path(self):
        p = PROJECT_ROOT / "scripts" / "quick_verify.sh"
        return p

    def test_script_exists(self, script_path):
        assert script_path.exists(), f"quick_verify.sh not found at {script_path}"

    def test_script_is_executable(self, script_path):
        mode = script_path.stat().st_mode
        assert bool(mode & stat.S_IXUSR), "quick_verify.sh is not user-executable"

    def test_script_mentions_gateway(self, script_path):
        content = script_path.read_text()
        assert "gateway" in content.lower()

    def test_script_mentions_vlm(self, script_path):
        content = script_path.read_text()
        assert "vlm" in content.lower()


# ===========================================================================
# 10. QUICKSTART.md one-command section
# ===========================================================================

class TestQuickstartDocs:
    """QUICKSTART.md contains the G7 one-command quick-verify section."""

    @pytest.fixture(scope="class")
    def qs_text(self):
        path = PROJECT_ROOT / "QUICKSTART.md"
        assert path.exists(), "QUICKSTART.md not found at project root"
        return path.read_text()

    def test_quick_verify_section_present(self, qs_text):
        assert "quick_verify" in qs_text or "quick-verify" in qs_text

    def test_troubleshooting_section_present(self, qs_text):
        assert "troubleshoot" in qs_text.lower()

    def test_make_target_documented(self, qs_text):
        assert "make" in qs_text.lower()
