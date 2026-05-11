"""
tests/test_pr4_status_board_v2.py
===================================
Tests for PR-4: Status Board V2 (Topology + Runtime Projection).

Coverage
--------
1. ProjectionReader
   - parse a valid projection JSON dict (file mode)
   - parse from a JSON string via stdin cache
   - raise ProjectionReadError on missing required fields
   - raise ProjectionReadError when JSON is not a dict
   - all-sources-fail raises ProjectionReadError

2. Surface rendering (snapshot text formatting)
   - PhaseSurface: silent / liminal / manifest
   - DomainSurface: local / cross_device / transition / None
   - TopologySurface: with weights, without weights, primary marker
   - DeviceSurface: with devices, without devices, with task summary
   - MetricsSurface: with values, with None values

3. StatusBoardV2App.render_once (integration)
   - full board contains all expected field values
   - render_offline contains OFFLINE text

4. Endpoint: GET /api/v1/projection/runtime
   - returns 200 with a valid RuntimeProjection structure (required keys)
   - response body contains tri_state_phase
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_PROJECTION: Dict[str, Any] = {
    "tri_state_phase": "liminal",
    "runtime_domain": "local",
    "presence_intensity": 0.6,
    "coherence": 0.75,
    "collapse_tendency": 0.3,
    "retreat_tendency": 0.1,
    "primary_model_id": "gpt-4o",
    "support_model_ids": ["claude-3", "local-vlm"],
    "active_weights": {
        "gpt-4o": 0.9,
        "claude-3": 0.6,
        "local-vlm": 0.4,
    },
    "route_reason": "Native multimodal preferred in liminal",
    "active_device_ids": ["desktop-win"],
    "execution_stage": "planning",
    "current_task_summary": "Drafting email",
    "timestamp": 1711533600.0,
}

_MINIMAL_PROJECTION: Dict[str, Any] = {
    "tri_state_phase": "silent",
    "runtime_domain": None,
    "presence_intensity": None,
    "coherence": None,
    "collapse_tendency": None,
    "retreat_tendency": None,
    "primary_model_id": None,
    "support_model_ids": [],
    "active_weights": {},
    "route_reason": None,
    "active_device_ids": [],
    "execution_stage": None,
    "current_task_summary": None,
    "timestamp": 1711533600.0,
}

_RUNTIME_TRUTH_PAYLOAD: Dict[str, Any] = {
    "compiled_at": 1711533601.0,
    "tri_state_phase": "manifest",
    "primary_model_id": "gpt-4.1",
    "continuum": {
        "tri_state_phase": "manifest",
        "runtime_domain": "cross_device",
        "presence_intensity": 0.82,
        "coherence": 0.9,
        "collapse_tendency": 0.12,
        "retreat_tendency": 0.04,
    },
    "topology": {
        "primary_model": "gpt-4.1",
        "support_models": ["claude-3-5-sonnet"],
        "active_weights": {"gpt-4.1": 0.95},
        "route_reason": "canonical-route",
    },
}

_DESKTOP_STATUS_BOARD_PAYLOAD: Dict[str, Any] = {
    "integrated_at": 1711533602.0,
    "topology_projection": {
        "primary_model_id": "qwen-vl",
        "support_model_ids": ["deepseek-chat"],
        "active_weights": {"qwen-vl": 0.77},
        "route_reason": "desktop-topology-route",
    },
    "operational_state_board": {
        "authority": "core.v2_unified_state_contract::v2-side-executable-state-contract",
        "contract_version": "1.0.0",
        "categories": [
            {
                "category_id": "registration_state",
                "label": "Registration state",
                "state": "ready",
                "summary": "Registration is structurally ready on the V2 side.",
                "source_of_truth_boundary": "v2_authoritative",
            },
            {
                "category_id": "minimum_access_admission_verdict",
                "label": "Operational acceptance state",
                "state": "acceptable",
                "summary": "System is operationally acceptable on canonical V2 terms.",
                "source_of_truth_boundary": "joint_cross_repo_derived",
            },
        ],
        "dependencies_and_blockers": {
            "blocked": False,
            "incomplete": False,
            "waiting_dependencies": [],
        },
    },
}

# ---------------------------------------------------------------------------
# 1. ProjectionReader tests
# ---------------------------------------------------------------------------


class TestProjectionReaderFile:
    """ProjectionReader reads from a JSON file."""

    def test_read_valid_file(self, tmp_path):
        f = tmp_path / "proj.json"
        f.write_text(json.dumps(_SAMPLE_PROJECTION))
        from windows_client.status_board_v2.projection_reader import ProjectionReader
        reader = ProjectionReader(base_url=None, file_path=str(f))
        result = reader.read()
        assert result["tri_state_phase"] == "liminal"
        assert result["primary_model_id"] == "gpt-4o"
        assert result["active_weights"]["gpt-4o"] == pytest.approx(0.9)

    def test_read_minimal_file(self, tmp_path):
        f = tmp_path / "minimal.json"
        f.write_text(json.dumps(_MINIMAL_PROJECTION))
        from windows_client.status_board_v2.projection_reader import ProjectionReader
        reader = ProjectionReader(base_url=None, file_path=str(f))
        result = reader.read()
        assert result["tri_state_phase"] == "silent"
        assert result["primary_model_id"] is None
        assert result["active_weights"] == {}

    def test_runtime_truth_payload_normalizes_to_runtime_projection(self):
        from windows_client.status_board_v2.projection_reader import (
            _normalize_board_projection_payload,
            RUNTIME_TRUTH_ENDPOINT,
        )
        result = _normalize_board_projection_payload(
            dict(_RUNTIME_TRUTH_PAYLOAD),
            RUNTIME_TRUTH_ENDPOINT,
        )
        assert result["tri_state_phase"] == "manifest"
        assert result["runtime_domain"] == "cross_device"
        assert result["primary_model_id"] == "gpt-4.1"
        assert result["support_model_ids"] == ["claude-3-5-sonnet"]

    def test_desktop_status_board_payload_normalizes_to_runtime_projection(self):
        from windows_client.status_board_v2.projection_reader import (
            _normalize_board_projection_payload,
            DESKTOP_STATUS_BOARD_ENDPOINT,
        )
        result = _normalize_board_projection_payload(
            dict(_DESKTOP_STATUS_BOARD_PAYLOAD),
            DESKTOP_STATUS_BOARD_ENDPOINT,
        )
        assert result["tri_state_phase"] == "silent"
        assert result["primary_model_id"] == "qwen-vl"
        assert result["support_model_ids"] == ["deepseek-chat"]
        assert "operational_state_board" in result
        assert result["operational_state_board"]["categories"][0]["category_id"] == "registration_state"

    def test_missing_required_field_raises(self, tmp_path):
        bad = dict(_SAMPLE_PROJECTION)
        del bad["tri_state_phase"]
        f = tmp_path / "bad.json"
        f.write_text(json.dumps(bad))
        from windows_client.status_board_v2.projection_reader import (
            ProjectionReader,
            ProjectionReadError,
        )
        reader = ProjectionReader(base_url=None, file_path=str(f))
        with pytest.raises(ProjectionReadError, match="tri_state_phase"):
            reader.read()

    def test_non_dict_raises(self, tmp_path):
        f = tmp_path / "list.json"
        f.write_text(json.dumps([1, 2, 3]))
        from windows_client.status_board_v2.projection_reader import (
            ProjectionReader,
            ProjectionReadError,
        )
        reader = ProjectionReader(base_url=None, file_path=str(f))
        with pytest.raises(ProjectionReadError, match="Expected a JSON object"):
            reader.read()


class TestProjectionReaderStdin:
    """ProjectionReader reads from stdin cache."""

    def test_stdin_cache(self):
        from windows_client.status_board_v2.projection_reader import ProjectionReader
        reader = ProjectionReader(base_url=None, from_stdin=True)
        # Pre-load the cache to avoid actually reading stdin in tests.
        reader._stdin_cache = dict(_SAMPLE_PROJECTION)
        result = reader.read()
        assert result["tri_state_phase"] == "liminal"

    def test_stdin_cache_stable_across_reads(self):
        from windows_client.status_board_v2.projection_reader import ProjectionReader
        reader = ProjectionReader(base_url=None, from_stdin=True)
        reader._stdin_cache = dict(_SAMPLE_PROJECTION)
        first = reader.read()
        second = reader.read()
        assert first == second


class TestProjectionReaderAllFail:
    """ProjectionReader raises when all sources fail."""

    def test_no_source_raises(self):
        from windows_client.status_board_v2.projection_reader import (
            ProjectionReader,
            ProjectionReadError,
        )
        reader = ProjectionReader(base_url=None, file_path=None, from_stdin=False)
        with pytest.raises(ProjectionReadError):
            reader.read()

    def test_bad_url_raises(self):
        from windows_client.status_board_v2.projection_reader import (
            ProjectionReader,
            ProjectionReadError,
        )
        reader = ProjectionReader(
            base_url="http://127.0.0.1:1",  # port 1 should be unreachable
            file_path=None,
            from_stdin=False,
            timeout=0.1,
        )
        with pytest.raises(ProjectionReadError):
            reader.read()

    def test_http_read_prefers_runtime_truth_then_falls_back(self):
        from windows_client.status_board_v2.projection_reader import (
            ProjectionReader,
            RUNTIME_TRUTH_ENDPOINT,
            PROJECTION_ENDPOINT,
        )
        reader = ProjectionReader(base_url="http://127.0.0.1:8299")

        def _fake_read(endpoint: str):
            if endpoint == RUNTIME_TRUTH_ENDPOINT:
                raise RuntimeError("runtime-truth unavailable")
            if endpoint == PROJECTION_ENDPOINT:
                return dict(_SAMPLE_PROJECTION)
            raise RuntimeError("desktop-status-board unavailable")

        with patch.object(reader, "_read_http_endpoint", side_effect=_fake_read):
            result = reader.read()
        assert result["tri_state_phase"] == "liminal"
        assert reader.last_http_endpoint == PROJECTION_ENDPOINT


# ---------------------------------------------------------------------------
# 2. Surface rendering tests
# ---------------------------------------------------------------------------

class TestPhaseSurface:
    """PhaseSurface snapshot text formatting."""

    @pytest.fixture(autouse=True)
    def _disable_ansi(self):
        import windows_client.status_board_v2._ansi as ansi_mod
        orig = ansi_mod.ANSI_ENABLED
        ansi_mod.ANSI_ENABLED = False
        yield
        ansi_mod.ANSI_ENABLED = orig

    def test_render_silent(self):
        from windows_client.status_board_v2.phase_surface import PhaseSurface
        out = PhaseSurface().render({"tri_state_phase": "silent"})
        assert "SILENT" in out
        assert "Phase" in out

    def test_render_liminal(self):
        from windows_client.status_board_v2.phase_surface import PhaseSurface
        out = PhaseSurface().render({"tri_state_phase": "liminal"})
        assert "LIMINAL" in out

    def test_render_manifest(self):
        from windows_client.status_board_v2.phase_surface import PhaseSurface
        out = PhaseSurface().render({"tri_state_phase": "manifest"})
        assert "MANIFEST" in out

    def test_render_unknown_phase(self):
        from windows_client.status_board_v2.phase_surface import PhaseSurface
        out = PhaseSurface().render({"tri_state_phase": "unknown_phase"})
        # Should not crash; phase key present
        assert "Phase" in out


class TestDomainSurface:
    """DomainSurface snapshot text formatting."""

    @pytest.fixture(autouse=True)
    def _disable_ansi(self):
        import windows_client.status_board_v2._ansi as ansi_mod
        orig = ansi_mod.ANSI_ENABLED
        ansi_mod.ANSI_ENABLED = False
        yield
        ansi_mod.ANSI_ENABLED = orig

    def test_render_local(self):
        from windows_client.status_board_v2.domain_surface import DomainSurface
        out = DomainSurface().render({"runtime_domain": "local"})
        assert "LOCAL" in out

    def test_render_cross_device(self):
        from windows_client.status_board_v2.domain_surface import DomainSurface
        out = DomainSurface().render({"runtime_domain": "cross_device"})
        assert "CROSS_DEVICE" in out

    def test_render_transition(self):
        from windows_client.status_board_v2.domain_surface import DomainSurface
        out = DomainSurface().render({"runtime_domain": "transition"})
        assert "TRANSITION" in out

    def test_render_none_domain(self):
        from windows_client.status_board_v2.domain_surface import DomainSurface
        out = DomainSurface().render({"runtime_domain": None})
        assert "UNKNOWN" in out.upper() or "unknown" in out.lower()


class TestTopologySurface:
    """TopologySurface snapshot text formatting."""

    @pytest.fixture(autouse=True)
    def _disable_ansi(self):
        import windows_client.status_board_v2._ansi as ansi_mod
        orig = ansi_mod.ANSI_ENABLED
        ansi_mod.ANSI_ENABLED = False
        yield
        ansi_mod.ANSI_ENABLED = orig

    def test_render_with_weights(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_SAMPLE_PROJECTION)
        assert "gpt-4o" in out
        assert "MAIN ROUTE" in out  # Updated: header is now "MAIN ROUTE" (native-multimodal-first)
        # Weight bars rendered
        assert "█" in out or "Weights" in out

    def test_render_primary_marker(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_SAMPLE_PROJECTION)
        # Primary model should be marked with ★
        assert "★" in out

    def test_render_no_weights(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        proj = dict(_MINIMAL_PROJECTION)
        out = TopologySurface().render(proj)
        assert "no topology data" in out

    def test_render_support_models(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_SAMPLE_PROJECTION)
        assert "claude-3" in out

    def test_render_route_reason(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_SAMPLE_PROJECTION)
        assert "Native multimodal" in out

    def test_render_long_reason_truncated(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        proj = dict(_SAMPLE_PROJECTION, route_reason="x" * 100)
        out = TopologySurface().render(proj)
        assert "..." in out


class TestDeviceSurface:
    """DeviceSurface snapshot text formatting."""

    @pytest.fixture(autouse=True)
    def _disable_ansi(self):
        import windows_client.status_board_v2._ansi as ansi_mod
        orig = ansi_mod.ANSI_ENABLED
        ansi_mod.ANSI_ENABLED = False
        yield
        ansi_mod.ANSI_ENABLED = orig

    def test_render_with_devices(self):
        from windows_client.status_board_v2.device_surface import DeviceSurface
        out = DeviceSurface().render(_SAMPLE_PROJECTION)
        assert "desktop-win" in out

    def test_render_no_devices(self):
        from windows_client.status_board_v2.device_surface import DeviceSurface
        out = DeviceSurface().render(_MINIMAL_PROJECTION)
        assert "none active" in out

    def test_render_execution_stage(self):
        from windows_client.status_board_v2.device_surface import DeviceSurface
        out = DeviceSurface().render(_SAMPLE_PROJECTION)
        assert "planning" in out

    def test_render_idle_stage(self):
        from windows_client.status_board_v2.device_surface import DeviceSurface
        out = DeviceSurface().render(_MINIMAL_PROJECTION)
        assert "idle" in out

    def test_render_task_summary(self):
        from windows_client.status_board_v2.device_surface import DeviceSurface
        out = DeviceSurface().render(_SAMPLE_PROJECTION)
        assert "Drafting email" in out

    def test_render_long_task_truncated(self):
        from windows_client.status_board_v2.device_surface import DeviceSurface
        proj = dict(_SAMPLE_PROJECTION, current_task_summary="t" * 100)
        out = DeviceSurface().render(proj)
        assert "..." in out


class TestMetricsSurface:
    """MetricsSurface snapshot text formatting."""

    @pytest.fixture(autouse=True)
    def _disable_ansi(self):
        import windows_client.status_board_v2._ansi as ansi_mod
        orig = ansi_mod.ANSI_ENABLED
        ansi_mod.ANSI_ENABLED = False
        yield
        ansi_mod.ANSI_ENABLED = orig

    def test_render_with_values(self):
        from windows_client.status_board_v2.metrics_surface import MetricsSurface
        out = MetricsSurface().render(_SAMPLE_PROJECTION)
        assert "Presence" in out
        assert "Coherence" in out
        assert "Collapse" in out
        assert "Retreat" in out
        # Bar characters present
        assert "█" in out

    def test_render_none_values(self):
        from windows_client.status_board_v2.metrics_surface import MetricsSurface
        out = MetricsSurface().render(_MINIMAL_PROJECTION)
        assert "(n/a)" in out

    def test_render_boundary_zero(self):
        from windows_client.status_board_v2.metrics_surface import MetricsSurface
        proj = dict(
            _MINIMAL_PROJECTION,
            presence_intensity=0.0,
            coherence=0.0,
            collapse_tendency=0.0,
            retreat_tendency=0.0,
        )
        out = MetricsSurface().render(proj)
        assert "0.000" in out

    def test_render_boundary_one(self):
        from windows_client.status_board_v2.metrics_surface import MetricsSurface
        proj = dict(
            _MINIMAL_PROJECTION,
            presence_intensity=1.0,
            coherence=1.0,
            collapse_tendency=1.0,
            retreat_tendency=1.0,
        )
        out = MetricsSurface().render(proj)
        assert "1.000" in out


# ---------------------------------------------------------------------------
# 3. StatusBoardV2App integration tests
# ---------------------------------------------------------------------------

class TestStatusBoardV2App:
    """StatusBoardV2App.render_once integration tests."""

    @pytest.fixture(autouse=True)
    def _disable_ansi(self):
        import windows_client.status_board_v2._ansi as ansi_mod
        orig = ansi_mod.ANSI_ENABLED
        ansi_mod.ANSI_ENABLED = False
        yield
        ansi_mod.ANSI_ENABLED = orig

    def test_render_once_contains_phase(self):
        from windows_client.status_board_v2.app import StatusBoardV2App
        app = StatusBoardV2App(no_color=True)
        out = app.render_once(_SAMPLE_PROJECTION)
        assert "LIMINAL" in out

    def test_render_once_contains_domain(self):
        from windows_client.status_board_v2.app import StatusBoardV2App
        app = StatusBoardV2App(no_color=True)
        out = app.render_once(_SAMPLE_PROJECTION)
        assert "LOCAL" in out

    def test_render_once_contains_primary_model(self):
        from windows_client.status_board_v2.app import StatusBoardV2App
        app = StatusBoardV2App(no_color=True)
        out = app.render_once(_SAMPLE_PROJECTION)
        assert "gpt-4o" in out

    def test_render_once_contains_device(self):
        from windows_client.status_board_v2.app import StatusBoardV2App
        app = StatusBoardV2App(no_color=True)
        out = app.render_once(_SAMPLE_PROJECTION)
        assert "desktop-win" in out

    def test_render_once_contains_metrics(self):
        from windows_client.status_board_v2.app import StatusBoardV2App
        app = StatusBoardV2App(no_color=True)
        out = app.render_once(_SAMPLE_PROJECTION)
        assert "Coherence" in out

    def test_render_once_includes_operational_state_board_when_present(self):
        from windows_client.status_board_v2.app import StatusBoardV2App
        app = StatusBoardV2App(no_color=True)
        projection = dict(_SAMPLE_PROJECTION)
        projection["operational_state_board"] = _DESKTOP_STATUS_BOARD_PAYLOAD["operational_state_board"]
        out = app.render_once(projection)
        assert "Operational State Board" in out
        assert "Registration state" in out
        assert "joint_cross_repo_derived" in out

    def test_render_once_contains_board_title(self):
        # PR-8: board is now a desktop control surface, not read-only.
        # Validates the board title is rendered in each frame.
        from windows_client.status_board_v2.app import StatusBoardV2App
        app = StatusBoardV2App(no_color=True)
        out = app.render_once(_SAMPLE_PROJECTION)
        assert "Status Board V2" in out

    def test_render_once_source_defaults_to_runtime_truth_endpoint(self):
        from windows_client.status_board_v2.app import StatusBoardV2App
        app = StatusBoardV2App(no_color=True)
        out = app.render_once(_SAMPLE_PROJECTION)
        assert "/api/v1/projection/runtime-truth" in out

    def test_render_offline_contains_offline(self):
        from windows_client.status_board_v2.app import StatusBoardV2App
        app = StatusBoardV2App(no_color=True)
        out = app.render_offline("connection refused")
        assert "OFFLINE" in out
        assert "connection refused" in out

    def test_render_once_timestamp_shown(self):
        from windows_client.status_board_v2.app import StatusBoardV2App
        app = StatusBoardV2App(no_color=True)
        out = app.render_once(_SAMPLE_PROJECTION)
        # Timestamp formatted as HH:MM:SS should be in the board.
        assert "Updated" in out

    def test_render_once_no_chat_input_text(self):
        """Board title must not contain chat-like prompts."""
        from windows_client.status_board_v2.app import StatusBoardV2App
        app = StatusBoardV2App(no_color=True)
        out = app.render_once(_SAMPLE_PROJECTION)
        assert ">" not in out or "→" in out  # directional arrows ok, prompt chars not expected
        # The key guarantee: no chat box language
        assert "Type a message" not in out
        assert "Send" not in out


# ---------------------------------------------------------------------------
# 4. Projection endpoint tests
# ---------------------------------------------------------------------------

class TestProjectionEndpoint:
    """GET /api/v1/projection/runtime returns a valid RuntimeProjection dict."""

    def _call_endpoint(self):
        """Import and call the projection assembly function directly."""
        from core.routes.projection import _assemble_projection
        return _assemble_projection()

    def test_endpoint_returns_dict(self):
        result = self._call_endpoint()
        assert isinstance(result, dict)

    def test_endpoint_has_required_keys(self):
        from windows_client.status_board_v2.projection_reader import _REQUIRED_FIELDS
        result = self._call_endpoint()
        for key in _REQUIRED_FIELDS:
            assert key in result, f"Missing required key: {key!r}"

    def test_endpoint_tri_state_phase_is_string(self):
        result = self._call_endpoint()
        assert isinstance(result["tri_state_phase"], str)
        assert result["tri_state_phase"] in ("silent", "liminal", "manifest")

    def test_endpoint_support_model_ids_is_list(self):
        result = self._call_endpoint()
        assert isinstance(result["support_model_ids"], list)

    def test_endpoint_active_weights_is_dict(self):
        result = self._call_endpoint()
        assert isinstance(result["active_weights"], dict)

    def test_endpoint_active_device_ids_is_list(self):
        result = self._call_endpoint()
        assert isinstance(result["active_device_ids"], list)

    def test_endpoint_timestamp_is_float(self):
        result = self._call_endpoint()
        assert isinstance(result["timestamp"], (int, float))

    def test_endpoint_creates_fastapi_router(self):
        """create_router() returns an APIRouter (smoke test for registration)."""
        from core.routes.projection import create_router
        from fastapi import APIRouter
        router = create_router()
        assert isinstance(router, APIRouter)
        # Check the endpoint is registered.
        routes = [r.path for r in router.routes]
        assert "/api/v1/projection/runtime" in routes

    def test_endpoint_fallback_payload_valid(self):
        """_minimal_fallback_payload returns a valid minimal projection."""
        from core.routes.projection import _minimal_fallback_payload
        from windows_client.status_board_v2.projection_reader import _REQUIRED_FIELDS
        payload = _minimal_fallback_payload()
        for key in _REQUIRED_FIELDS:
            assert key in payload, f"Fallback missing key: {key!r}"
        assert payload["tri_state_phase"] == "silent"
