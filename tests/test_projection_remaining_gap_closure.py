from __future__ import annotations


def test_runtime_truth_payload_fallback_outward_truth_is_non_null(monkeypatch):
    from core.routes import projection as projection_routes

    def _explode():
        raise RuntimeError("outward truth unavailable")

    monkeypatch.setattr(projection_routes, "_compile_outward_truth", _explode)
    payload = projection_routes._assemble_runtime_truth_payload()

    assert payload["outward_truth"] is not None
    assert isinstance(payload["outward_truth"], dict)
    assert payload["outward_truth"]["operator_snapshot"]["active_task_count"] == 0
    assert isinstance(payload["stale_or_cached_summary"]["fallback"], bool)
    assert payload["control_plane_contract"]["surface"] == "board"
    assert "field_typing" in payload["control_plane_contract"]


def test_minimal_desktop_status_board_fallback_has_non_null_outward_truth():
    from core.routes.projection import _minimal_desktop_status_board_fallback

    payload = _minimal_desktop_status_board_fallback()

    assert payload["outward_truth"] is not None
    assert isinstance(payload["outward_truth"], dict)
    assert payload["task_truth"]["source"] == "fallback"
    assert payload["stale_or_cached_summary"]["desktop_payload_fallback"] is True
    assert payload["control_plane_contract"]["surface"] == "desktop_projection"
