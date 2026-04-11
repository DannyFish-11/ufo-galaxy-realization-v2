#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations


def test_minimal_fallback_payload_marks_non_live_runtime_anchor():
    from core.routes.projection import _minimal_fallback_payload

    payload = _minimal_fallback_payload()
    assert payload["tri_state_phase"] == "silent"
    assert "projection_authority_context" in payload
    ctx = payload["projection_authority_context"]
    assert ctx["continuum_is_live_runtime"] is False
    assert ctx["runtime_state_anchor"] == "not_live_runtime"


def test_assemble_projection_uses_fallback_when_continuum_not_live(monkeypatch):
    from core.routes import projection as mod

    monkeypatch.setattr(
        mod,
        "_get_continuum_state_with_source",
        lambda: ({"tri_state_phase": "silent"}, "synthetic_formless_fallback", False),
    )
    payload = mod._assemble_projection()

    assert payload["tri_state_phase"] == "silent"
    ctx = payload["projection_authority_context"]
    assert ctx["continuum_is_live_runtime"] is False
    assert ctx["runtime_state_anchor"] == "not_live_runtime"
