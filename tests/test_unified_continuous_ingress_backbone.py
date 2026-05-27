"""tests/test_unified_continuous_ingress_backbone.py

Behavioral tests proving that the unified canonical continuous ingress backbone
is a *mainchain unification*, not a transport layer extension.

Four test groups:
  1. Unified ingress construction — two or more families in one structure.
  2. Stream mainline consumption — OpenClawd.process-path consumes the model.
  3. Continuous behavior difference — with/without stream changes mainchain outcome.
  4. Transport-to-cognition promotion — WebRTC path enters canonical cognition role.
"""

from __future__ import annotations

import pytest
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Helper imports
# ---------------------------------------------------------------------------

from core.unified_continuous_ingress import (
    FAMILY_ANDROID_DEVICE_STREAM,
    FAMILY_DESKTOP_PERCEPTION_SESSION,
    FAMILY_WEBRTC_STREAM,
    FUSION_STRATEGY_DISCRETE,
    FUSION_STRATEGY_MULTISTREAM,
    FUSION_STRATEGY_SINGLE_STREAM,
    PLANNING_READINESS_CONTINUOUS_MAINLINE,
    PLANNING_READINESS_NONE,
    PLANNING_READINESS_STREAM_ASSISTED,
    UNIFIED_CONTINUOUS_INGRESS_AUTHORITY,
    UNIFIED_CONTINUOUS_INGRESS_SENTINEL,
    ContinuousIngressEntry,
    UnifiedContinuousIngressModel,
    assemble_unified_continuous_ingress,
)


# ===========================================================================
# Group 1 — Unified ingress construction test
# Verifies that two or more continuous ingress families enter the same
# canonical structure (UnifiedContinuousIngressModel) via assembly.
# ===========================================================================


def test_unified_ingress_model_contains_all_three_families():
    """assemble_unified_continuous_ingress must always produce entries for all
    three canonical families — webrtc_stream, android_device_stream, and
    desktop_perception_session — regardless of activity state."""
    model = assemble_unified_continuous_ingress()

    family_names = [e.family for e in model.entries]
    assert FAMILY_WEBRTC_STREAM in family_names, (
        "unified model must contain a webrtc_stream entry"
    )
    assert FAMILY_ANDROID_DEVICE_STREAM in family_names, (
        "unified model must contain an android_device_stream entry"
    )
    assert FAMILY_DESKTOP_PERCEPTION_SESSION in family_names, (
        "unified model must contain a desktop_perception_session entry"
    )


def test_unified_ingress_construction_with_two_active_families():
    """When WebRTC stream is active (via stream_runtime_status) and the desktop
    perception session has a live frame, both families must appear together in
    the *same* UnifiedContinuousIngressModel — proving two-family unification."""
    model = assemble_unified_continuous_ingress(
        stream_runtime_status={
            "stream_state": "active",
            "stream_active_for_routing": True,
            "stream_fallback_required": False,
        },
        desktop_native_ingress_backbone=None,
        desktop_perception_frame_available=True,
    )

    assert model.authority == UNIFIED_CONTINUOUS_INGRESS_AUTHORITY, (
        "model authority sentinel must match"
    )
    assert model.sentinel == UNIFIED_CONTINUOUS_INGRESS_SENTINEL

    # Both families must be active
    assert FAMILY_WEBRTC_STREAM in model.active_families, (
        "webrtc_stream must be active when stream_active_for_routing=True"
    )
    assert FAMILY_DESKTOP_PERCEPTION_SESSION in model.active_families, (
        "desktop_perception_session must be active when frame is available"
    )

    # At least two families active → multistream strategy
    assert model.active_family_count >= 2
    assert model.multimodal_fusion_strategy == FUSION_STRATEGY_MULTISTREAM, (
        "two active families must produce continuous_multistream_cognition_fusion strategy"
    )


def test_unified_ingress_construction_serialises_cleanly():
    """to_dict() must contain all expected keys so downstream consumers can
    inspect the structure without raising exceptions."""
    model = assemble_unified_continuous_ingress(
        stream_runtime_status={
            "stream_state": "active",
            "stream_active_for_routing": True,
            "stream_fallback_required": False,
        },
        desktop_perception_frame_available=False,
    )
    d = model.to_dict()

    required_keys = {
        "authority",
        "sentinel",
        "entries",
        "active_families",
        "is_mainline_active",
        "active_family_count",
        "multimodal_fusion_strategy",
        "planning_readiness",
        "cognition_promotion_evidence",
    }
    for key in required_keys:
        assert key in d, f"to_dict() must contain key '{key}'"

    # entries list must have one dict per family
    assert isinstance(d["entries"], list)
    assert len(d["entries"]) == 3, "model must always carry all three family entries"


# ===========================================================================
# Group 2 — Stream mainline consumption test
# Verifies that OpenClawd._build_canonical_perception_state() consumes the
# UnifiedContinuousIngressModel and surfaces it in the canonical perception dict.
# ===========================================================================


def test_canonical_perception_contains_unified_ingress_when_stream_active():
    """When stream_runtime_status signals an active stream, the canonical
    perception dict produced by OpenClawd._build_canonical_perception_state()
    must contain the 'unified_continuous_ingress' key with authority/sentinel
    matching UnifiedContinuousIngressModel."""
    from core.openclawd import OpenClawd

    clawd = OpenClawd.__new__(OpenClawd)

    perception = clawd._build_canonical_perception_state(
        runtime_session_id="test-rs-001",
        trace_id="test-trace-001",
        stream_runtime_status={
            "stream_state": "active",
            "stream_active_for_routing": True,
            "stream_fallback_required": False,
        },
    )

    assert perception is not None, "_build_canonical_perception_state must not return None"
    assert "unified_continuous_ingress" in perception, (
        "canonical perception must embed unified_continuous_ingress when stream is active"
    )

    uci = perception["unified_continuous_ingress"]
    assert uci.get("authority") == UNIFIED_CONTINUOUS_INGRESS_AUTHORITY, (
        "embedded unified_continuous_ingress must carry the canonical authority sentinel"
    )
    assert uci.get("sentinel") == UNIFIED_CONTINUOUS_INGRESS_SENTINEL


def test_canonical_perception_contains_unified_ingress_even_when_stream_inactive():
    """unified_continuous_ingress must be embedded in canonical perception even
    when no stream is active — the model is always assembled, just with
    is_mainline_active=False and fusion_strategy=discrete_request_bound."""
    from core.openclawd import OpenClawd

    clawd = OpenClawd.__new__(OpenClawd)

    perception = clawd._build_canonical_perception_state(
        runtime_session_id="test-rs-002",
        trace_id="test-trace-002",
        stream_runtime_status={
            "stream_state": "discrete_fallback",
            "stream_active_for_routing": False,
            "stream_fallback_required": True,
        },
    )

    assert perception is not None
    assert "unified_continuous_ingress" in perception, (
        "unified_continuous_ingress must always be assembled in canonical perception"
    )
    uci = perception["unified_continuous_ingress"]
    assert uci.get("is_mainline_active") is False, (
        "is_mainline_active must be False when no stream is active"
    )


def test_canonical_perception_multimodal_fusion_strategy_is_present():
    """multimodal_fusion_strategy must be present in canonical perception so
    downstream planning and context-strategy steps have a named signal to
    consume — not just an implicit connection-state flag."""
    from core.openclawd import OpenClawd

    clawd = OpenClawd.__new__(OpenClawd)

    perception_active = clawd._build_canonical_perception_state(
        runtime_session_id="test-rs-003",
        trace_id="test-trace-003",
        stream_runtime_status={
            "stream_state": "active",
            "stream_active_for_routing": True,
            "stream_fallback_required": False,
        },
    )

    assert perception_active is not None
    assert "multimodal_fusion_strategy" in perception_active, (
        "canonical perception must carry multimodal_fusion_strategy"
    )
    assert "planning_readiness" in perception_active, (
        "canonical perception must carry planning_readiness"
    )


# ===========================================================================
# Group 3 — Continuous behavior difference test
# Verifies that stream *presence* changes mainchain behavior (not just
# connection status).  The behavioral signal is multimodal_fusion_strategy
# and planning_readiness — both must differ with vs. without active ingress.
# ===========================================================================


def test_continuous_behavior_difference_fusion_strategy():
    """multimodal_fusion_strategy must differ between:
    - Two continuous ingress families active → continuous_multistream_cognition_fusion
    - Zero continuous ingress families active → discrete_request_bound

    This is the primary machine-verifiable proof that continuous ingress
    changes mainchain behavior, not only connection state."""
    # Case A: two active families (WebRTC + desktop perception)
    model_with_streams = assemble_unified_continuous_ingress(
        stream_runtime_status={
            "stream_state": "active",
            "stream_active_for_routing": True,
            "stream_fallback_required": False,
        },
        desktop_perception_frame_available=True,
    )
    strategy_with = model_with_streams.multimodal_fusion_strategy

    # Case B: no active families
    model_no_streams = assemble_unified_continuous_ingress(
        stream_runtime_status={
            "stream_state": "discrete_fallback",
            "stream_active_for_routing": False,
            "stream_fallback_required": True,
        },
        desktop_perception_frame_available=False,
    )
    strategy_without = model_no_streams.multimodal_fusion_strategy

    assert strategy_with != strategy_without, (
        "multimodal_fusion_strategy must differ when continuous ingress is present vs. absent"
    )
    assert strategy_with == FUSION_STRATEGY_MULTISTREAM, (
        f"two active families must produce {FUSION_STRATEGY_MULTISTREAM}, got {strategy_with!r}"
    )
    assert strategy_without == FUSION_STRATEGY_DISCRETE, (
        f"zero active families must produce {FUSION_STRATEGY_DISCRETE}, got {strategy_without!r}"
    )


def test_continuous_behavior_difference_planning_readiness():
    """planning_readiness must differ between zero and two active families —
    proving that continuous ingress changes planning preparation in the mainchain."""
    model_two = assemble_unified_continuous_ingress(
        stream_runtime_status={
            "stream_state": "active",
            "stream_active_for_routing": True,
            "stream_fallback_required": False,
        },
        desktop_perception_frame_available=True,
    )
    model_zero = assemble_unified_continuous_ingress(
        stream_runtime_status=None,
        desktop_perception_frame_available=False,
    )

    assert model_two.planning_readiness != model_zero.planning_readiness, (
        "planning_readiness must differ between active and inactive continuous ingress"
    )
    assert model_two.planning_readiness == PLANNING_READINESS_CONTINUOUS_MAINLINE
    assert model_zero.planning_readiness == PLANNING_READINESS_NONE


def test_continuous_behavior_difference_reflected_in_canonical_perception():
    """The mainchain behavioral difference must be visible in the canonical
    perception dict produced by OpenClawd — not only in the model directly.
    This confirms that _build_canonical_perception_state is the real consumer."""
    from core.openclawd import OpenClawd

    clawd = OpenClawd.__new__(OpenClawd)

    # With active stream
    perc_active = clawd._build_canonical_perception_state(
        runtime_session_id="diff-rs-active",
        trace_id="diff-trace-active",
        stream_runtime_status={
            "stream_state": "active",
            "stream_active_for_routing": True,
            "stream_fallback_required": False,
        },
    )

    # Without stream
    perc_fallback = clawd._build_canonical_perception_state(
        runtime_session_id="diff-rs-fallback",
        trace_id="diff-trace-fallback",
        stream_runtime_status={
            "stream_state": "discrete_fallback",
            "stream_active_for_routing": False,
            "stream_fallback_required": True,
        },
    )

    assert perc_active is not None
    assert perc_fallback is not None

    # multimodal_fusion_strategy must differ
    strat_active = perc_active.get("multimodal_fusion_strategy")
    strat_fallback = perc_fallback.get("multimodal_fusion_strategy")
    assert strat_active != strat_fallback, (
        "multimodal_fusion_strategy in canonical perception must differ with vs. without stream"
    )

    # planning_readiness must differ
    plan_active = perc_active.get("planning_readiness")
    plan_fallback = perc_fallback.get("planning_readiness")
    assert plan_active != plan_fallback, (
        "planning_readiness in canonical perception must differ with vs. without stream"
    )

    # active_modalities must contain webrtc_stream only in the active case
    mods_active = perc_active.get("active_modalities", [])
    mods_fallback = perc_fallback.get("active_modalities", [])
    assert FAMILY_WEBRTC_STREAM in mods_active, (
        "webrtc_stream must appear in active_modalities when stream is active"
    )
    assert FAMILY_WEBRTC_STREAM not in mods_fallback, (
        "webrtc_stream must NOT appear in active_modalities when stream is inactive"
    )


# ===========================================================================
# Group 4 — Transport-to-cognition promotion test
# Verifies that paths previously classified as transport-only (WebRTC stream,
# Android device stream) have been promoted to canonical_cognition_ingress role
# and that this promotion is surfaced in cognition_promotion_evidence.
# ===========================================================================


def test_webrtc_transport_to_cognition_promotion_evidence():
    """The WebRTC stream entry must carry was_transport_promoted=True and
    cognition_role='canonical_cognition_ingress' — proving that the WebRTC path
    is no longer a pure media transport and has entered canonical cognition role."""
    model = assemble_unified_continuous_ingress(
        stream_runtime_status={
            "stream_state": "active",
            "stream_active_for_routing": True,
            "stream_fallback_required": False,
        },
    )

    webrtc_entry = next(
        (e for e in model.entries if e.family == FAMILY_WEBRTC_STREAM), None
    )
    assert webrtc_entry is not None, "webrtc_stream entry must be present in unified model"
    assert webrtc_entry.was_transport_promoted is True, (
        "webrtc_stream entry must have was_transport_promoted=True"
    )
    assert webrtc_entry.cognition_role == "canonical_cognition_ingress", (
        "webrtc_stream entry must have cognition_role='canonical_cognition_ingress'"
    )


def test_android_device_stream_transport_to_cognition_promotion_evidence():
    """The Android device stream entry must also carry was_transport_promoted=True
    and the canonical cognition role — confirming two transport-to-cognition
    promotions in a single unified model."""
    model = assemble_unified_continuous_ingress()

    android_entry = next(
        (e for e in model.entries if e.family == FAMILY_ANDROID_DEVICE_STREAM), None
    )
    assert android_entry is not None, "android_device_stream entry must be present"
    assert android_entry.was_transport_promoted is True, (
        "android_device_stream must have was_transport_promoted=True"
    )
    assert android_entry.cognition_role == "canonical_cognition_ingress", (
        "android_device_stream must have cognition_role='canonical_cognition_ingress'"
    )


def test_cognition_promotion_evidence_contains_two_promoted_families():
    """cognition_promotion_evidence must list at least two entries (WebRTC and
    Android device stream) — the two formerly transport-only families — even
    when neither is currently active.  This confirms structural promotion, not
    just runtime activity."""
    model = assemble_unified_continuous_ingress()
    evidence = model.cognition_promotion_evidence

    assert len(evidence) >= 2, (
        f"cognition_promotion_evidence must contain at least two promoted families, "
        f"got {len(evidence)}"
    )
    promoted_families = {rec["family"] for rec in evidence}
    assert FAMILY_WEBRTC_STREAM in promoted_families, (
        "webrtc_stream must appear in cognition_promotion_evidence"
    )
    assert FAMILY_ANDROID_DEVICE_STREAM in promoted_families, (
        "android_device_stream must appear in cognition_promotion_evidence"
    )
    for rec in evidence:
        assert rec.get("cognition_role") == "canonical_cognition_ingress", (
            f"all promoted families must carry cognition_role='canonical_cognition_ingress', "
            f"got {rec.get('cognition_role')!r} for {rec['family']}"
        )


def test_cognition_promotion_evidence_in_canonical_perception_dict():
    """The canonical perception dict must embed cognition_promotion_evidence
    via unified_continuous_ingress so the promotion is visible to any consumer
    of the mainchain perception object — not only to the assembly function."""
    from core.openclawd import OpenClawd

    clawd = OpenClawd.__new__(OpenClawd)

    perception = clawd._build_canonical_perception_state(
        runtime_session_id="promo-rs-001",
        trace_id="promo-trace-001",
        stream_runtime_status={
            "stream_state": "active",
            "stream_active_for_routing": True,
            "stream_fallback_required": False,
        },
    )

    assert perception is not None
    uci = perception.get("unified_continuous_ingress", {})
    evidence = uci.get("cognition_promotion_evidence", [])

    assert len(evidence) >= 2, (
        "canonical perception must carry cognition_promotion_evidence with ≥2 promoted families"
    )
    promoted_names = {rec["family"] for rec in evidence}
    assert FAMILY_WEBRTC_STREAM in promoted_names, (
        "webrtc_stream promotion must be visible in canonical perception"
    )
    assert FAMILY_ANDROID_DEVICE_STREAM in promoted_names, (
        "android_device_stream promotion must be visible in canonical perception"
    )
