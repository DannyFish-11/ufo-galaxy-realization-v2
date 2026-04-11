from __future__ import annotations


def test_minimal_fallback_payload_marks_metadata_only_scope():
    from core.routes.projection import _minimal_fallback_payload

    payload = _minimal_fallback_payload(
        reason="unit_test_fallback",
        continuum_source="unavailable",
    )
    ctx = payload["projection_truth_context"]
    assert ctx["authority_scope"] == "metadata_only_fallback"
    assert ctx["reflects_live_continuum_state"] is False
    assert ctx["fallback_reason"] == "unit_test_fallback"
    assert ctx["hard_authority_fields"] == ["tri_state_phase", "runtime_domain"]


def test_assemble_projection_surfaces_continuum_source_for_fallback(monkeypatch):
    from core.routes import projection as projection_route

    monkeypatch.setattr(
        projection_route,
        "_get_continuum_state_with_source",
        lambda: (None, "unavailable"),
    )
    payload = projection_route._assemble_projection()
    ctx = payload["projection_truth_context"]
    if ctx["fallback_reason"] == "continuum_unavailable":
        assert ctx["continuum_source"] == "unavailable"
    else:
        assert ctx["fallback_reason"] == "projection_imports_unavailable"
        assert ctx["continuum_source"] == "unknown"
