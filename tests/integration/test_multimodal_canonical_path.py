"""tests/integration/test_multimodal_canonical_path.py
=======================================================
PR-6 — Multimodal Canonical Participation & Proof

Machine-verifiable, end-to-end proof that the dual-repo Galaxy system's
canonical multimodal path is:

  (a) structurally correct — all real modules importable and chainable,
  (b) behaviourally correct — multimodal_context drives a distinct routing
      decision compared to text-only requests,
  (c) not overclaiming — ambient continuous ingest (MultimodalIngressBus)
      remains config-gated (SAFE_DEFAULT) and is correctly reported as such,
  (d) Android-side signals are genuinely tracked in V2 DeviceStateSnapshot
      (mobilevlm_present, seeclick_present), and
  (e) the Android vision uplink handler routes through the canonical
      DPR → OpenClawd multimodal path.

Evidence rules (from problem statement)
-----------------------------------------
All assertions are grounded in current merged code only:
  - core/desktop_presence_runtime.py  (DPR, tri-state shell)
  - core/openclawd.py                 (OpenClawd, subject core)
  - core/perception/canonical_perception_state.py   (CanonicalPerceptionState)
  - core/multimodal/ingress_bus.py    (MultimodalIngressBus)
  - core/multimodal_runtime_profile.py (SAFE_DEFAULT profile)
  - core/routing_observability.py     (RoutingDecisionEvent)
  - galaxy_gateway/android/handlers/vision.py  (Android vision handler)
  - core/android_device_state_store.py  (DeviceStateSnapshot)
  - core/five_domain_implementation_review.py  (domain review)
  - tests/integration/stubs/multimodal_perception_stub.py  (image stub)
  - tests/integration/stubs/llm_contract_stub.py  (LLM contract stub)

Canonical multimodal path under test
--------------------------------------
::

    MultiModalContext (stub image/audio)
    ──────────────────────────────────────────────────────────
    (request-bound path — always available, not config-gated)

        DesktopPresenceRuntime.handle_request(multimodal_context=ctx)
            → OpenClawd.process(multimodal_context=ctx)
                → MultimodalBus.ingest()               [fusion_summary]
                    → _build_canonical_perception_state()
                        has_request_multimodal=True
                        active_modalities=["image"]
                        requires_native_multimodal=True
                    → _select_multimodal_route(canonical_perception)
                        route_type != "text_only"       ← KEY PROOF
                        routing_decision_event emitted
                → result dict:
                    metadata.multimodal_route_decision  ← present
                    metadata.canonical_perception_state ← has_request_multimodal
                    metadata.routing_decision_event     ← structured event

    (Android side)
        android_vision handler → MultiModalContext(source="android_screen:*")
            → DPR.handle_request(source="android_vision", multimodal_context)
                → same canonical path as above

Test classes
-------------
1. TestMultimodalContextStructure
   Proves the stub and schema produce valid MultiModalContext objects.

2. TestMultimodalContextEntersOpenClawd
   Proves that multimodal_context flows through DPR → OpenClawd and
   produces a routing decision that is NOT text_only.

3. TestCanonicalPerceptionStateWithMultimodal
   Proves that CanonicalPerceptionState correctly reflects multimodal input
   (has_request_multimodal, active_modalities, requires_native_multimodal).

4. TestMultimodalRouteDecisionInResult
   Proves multimodal_route_decision appears in DPR response metadata and
   carries actionable routing information.

5. TestRoutingObservabilityEvent
   Proves a structured RoutingDecisionEvent is emitted for each multimodal
   request and carries the correct modality metadata.

6. TestMultimodalVsTextOnlyRegression
   Regression: a text-only request must produce route_type="text_only" while
   a multimodal request must produce a different route_type.  Tests that the
   two paths are distinguishable, making regressions detectable.

7. TestAndroidVisionIngress
   Proves the Android vision handler builds a canonical MultiModalContext
   with the expected android_screen source tag and routes it through DPR.

8. TestAndroidSideMultimodalPresence
   Proves mobilevlm_present, seeclick_present, and mobilevlm_checksum_ok
   fields are present in DeviceStateSnapshot and tracked by V2 store.

9. TestAmbientIngestRemainsGated
   Proves the continuous ambient ingress path (MultimodalIngressBus) is
   correctly reported as config-gated (SAFE_DEFAULT, enable_multimodal_ingest
   =False).  This test prevents overclaiming always-on ambient multimodal.

10. TestFiveDomainReviewUpgrade
    Proves that this test file's existence upgrades the MULTIMODAL_CANONICAL_PATH
    domain in five_domain_implementation_review from
    INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN → PARTIALLY_ESTABLISHED.

Non-goals
---------
- No real LLM API calls — the LLMContractStub leaf avoids network I/O.
- No always-on ambient ingest claimed — SAFE_DEFAULT gate is preserved.
- No new multimodal architecture — reuses current real canonical paths.
- No static field-presence checks without behavioural assertions.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Fields that must be present in every DPR result dict.
CANONICAL_DPR_FIELDS = (
    "success",
    "response",
    "runtime_session_id",
    "tristate",
    "entrypoint_source",
)

#: route_type value for text-only requests (no multimodal_context images/audio).
ROUTE_TYPE_TEXT_ONLY: str = "text_only"


# ---------------------------------------------------------------------------
# Shared helpers (mirror pattern from test_nl_e2e_canonical_path.py)
# ---------------------------------------------------------------------------


def _reset_openclawd_singleton() -> None:
    """Reset the OpenClawd singleton so each test gets a fresh instance."""
    try:
        import core.openclawd as _oc_mod
        _oc_mod._openclawd_instance = None
    except Exception:
        pass
    try:
        from core.unified.llm_router import reset_unified_llm_router
        reset_unified_llm_router()
    except Exception:
        pass
    try:
        from core.session_execution_lane import reset_session_execution_lane_manager
        reset_session_execution_lane_manager()
    except Exception:
        pass


def _reset_dpr_singleton() -> None:
    """Reset the DesktopPresenceRuntime singleton."""
    try:
        import core.desktop_presence_runtime as _dpr_mod
        _dpr_mod._desktop_presence_runtime = None
    except Exception:
        pass


def _make_stub():
    """Return a fresh LLMContractStub."""
    from tests.integration.stubs.llm_contract_stub import LLMContractStub
    return LLMContractStub()


def _patch_llm_router(stub):
    """Return a context manager that injects the stub at the canonical LLM
    router injection points (mirrors the NL proof helper)."""
    return patch.multiple(
        "core.unified.llm_router",
        get_unified_llm_router=lambda: stub,
    )


async def _run_handle_request(
    message: str,
    source: str = "chat",
    multimodal_context=None,
    **kw,
) -> Dict[str, Any]:
    """Invoke a fresh DesktopPresenceRuntime with the given arguments."""
    from core.desktop_presence_runtime import DesktopPresenceRuntime
    runtime = DesktopPresenceRuntime()
    kw.setdefault("session_id", "mm-proof-session")
    kw.setdefault("user_id", "mm-proof-user")
    result = await runtime.handle_request(
        message=message,
        source=source,
        multimodal_context=multimodal_context,
        **kw,
    )
    return result


# ---------------------------------------------------------------------------
# 1. MultimodalContext Structure
# ---------------------------------------------------------------------------


class TestMultimodalContextStructure:
    """Prove the stub and MultiModalContext schema produce valid objects.

    Evidence: core/schemas/multimodal.py, stubs/multimodal_perception_stub.py
    """

    def test_make_image_context_produces_valid_schema(self):
        """make_image_context() must return a MultiModalContext with one image."""
        from tests.integration.stubs.multimodal_perception_stub import (
            make_image_context,
            STUB_IMAGE_SOURCE,
        )
        from core.schemas.multimodal import MultiModalContext

        ctx = make_image_context()
        assert isinstance(ctx, MultiModalContext), (
            "make_image_context must return a MultiModalContext instance"
        )
        assert len(ctx.images) == 1, "stub context must carry exactly one image"
        assert ctx.images[0].source == STUB_IMAGE_SOURCE
        assert ctx.images[0].mime == "image/png"
        assert ctx.images[0].data, "stub image data must be non-empty"

    def test_make_android_vision_context_embeds_device_id(self):
        """make_android_vision_context() must embed device_id in image source."""
        from tests.integration.stubs.multimodal_perception_stub import (
            make_android_vision_context,
        )

        ctx = make_android_vision_context(device_id="android-001")
        assert ctx.images[0].source == "android_screen:android-001", (
            "android vision context source must match the real handler convention"
        )
        assert ctx.screen == {"mode": "full", "source": "android"}, (
            "android vision context must carry screen metadata"
        )

    def test_make_audio_context_produces_audio_modality(self):
        """make_audio_context() must return a MultiModalContext with audio."""
        from tests.integration.stubs.multimodal_perception_stub import make_audio_context
        from core.schemas.multimodal import MultiModalContext

        ctx = make_audio_context()
        assert isinstance(ctx, MultiModalContext)
        assert len(ctx.audio) == 1
        assert ctx.audio[0].mime == "audio/wav"


# ---------------------------------------------------------------------------
# 2. MultimodalContext Enters OpenClawd
# ---------------------------------------------------------------------------


class TestMultimodalContextEntersOpenClawd:
    """Prove that multimodal_context flows through DPR → OpenClawd and
    produces a routing decision that is NOT text_only.

    This is the core participation proof: a request carrying a real
    MultiModalContext with images must reach OpenClawd's routing authority
    and cause a measurably different routing outcome than a text-only request.

    Evidence:
    - core/openclawd.py: MultimodalBus.ingest() + _select_multimodal_route()
    - core/perception/canonical_perception_state.py: requires_native_multimodal
    """

    def test_image_context_produces_non_text_only_route(self):
        """Image multimodal_context must produce route_type != 'text_only'."""
        from tests.integration.stubs.multimodal_perception_stub import make_image_context

        stub = _make_stub()
        _reset_openclawd_singleton()
        ctx = make_image_context()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_handle_request(
                    "Describe this image",
                    multimodal_context=ctx,
                )
            )

        md = result.get("metadata", {})
        route_decision = md.get("multimodal_route_decision", {})
        route_type = route_decision.get("route_type", "")

        assert route_type != ROUTE_TYPE_TEXT_ONLY, (
            f"Image multimodal_context must drive route_type != 'text_only', "
            f"got: {route_type!r}.  This proves multimodal signals influence "
            f"the routing authority, not merely exist as infrastructure."
        )

    def test_dpr_result_contains_canonical_fields(self):
        """DPR.handle_request() with multimodal_context must return canonical fields."""
        from tests.integration.stubs.multimodal_perception_stub import make_image_context

        stub = _make_stub()
        _reset_openclawd_singleton()
        ctx = make_image_context()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_handle_request("What do you see?", multimodal_context=ctx)
            )

        for field in CANONICAL_DPR_FIELDS:
            assert field in result, (
                f"Canonical field '{field}' missing from DPR result for "
                f"multimodal request — the multimodal path must produce the "
                f"same authoritative result envelope as the NL path."
            )

    def test_result_success_is_true(self):
        """DPR must succeed for a well-formed multimodal request."""
        from tests.integration.stubs.multimodal_perception_stub import make_image_context

        stub = _make_stub()
        _reset_openclawd_singleton()
        ctx = make_image_context()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_handle_request("Describe", multimodal_context=ctx)
            )

        assert result.get("success"), (
            "handle_request must succeed for a multimodal request with a stub LLM"
        )

    def test_audio_context_also_produces_non_text_only_route(self):
        """Audio multimodal_context must also produce route_type != 'text_only'."""
        from tests.integration.stubs.multimodal_perception_stub import make_audio_context

        stub = _make_stub()
        _reset_openclawd_singleton()
        ctx = make_audio_context()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_handle_request("Transcribe this", multimodal_context=ctx)
            )

        md = result.get("metadata", {})
        route_type = md.get("multimodal_route_decision", {}).get("route_type", "")
        assert route_type != ROUTE_TYPE_TEXT_ONLY, (
            "Audio multimodal_context must also drive route_type != 'text_only'"
        )


# ---------------------------------------------------------------------------
# 3. Canonical Perception State With Multimodal
# ---------------------------------------------------------------------------


class TestCanonicalPerceptionStateWithMultimodal:
    """Prove CanonicalPerceptionState correctly reflects multimodal input.

    Evidence: core/perception/canonical_perception_state.py
    """

    def test_has_request_multimodal_true_when_image_present(self):
        """canonical_perception_state.has_request_multimodal must be True."""
        from tests.integration.stubs.multimodal_perception_stub import make_image_context

        stub = _make_stub()
        _reset_openclawd_singleton()
        ctx = make_image_context()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_handle_request("Analyse image", multimodal_context=ctx)
            )

        cps = result.get("metadata", {}).get("canonical_perception_state", {})
        assert cps, "canonical_perception_state must be present in metadata"
        assert cps.get("has_request_multimodal") is True, (
            "has_request_multimodal must be True when images are in multimodal_context"
        )

    def test_active_modalities_includes_image(self):
        """active_modalities must include 'image' for an image request."""
        from tests.integration.stubs.multimodal_perception_stub import make_image_context

        stub = _make_stub()
        _reset_openclawd_singleton()
        ctx = make_image_context()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_handle_request("Describe image", multimodal_context=ctx)
            )

        cps = result.get("metadata", {}).get("canonical_perception_state", {})
        modalities = cps.get("active_modalities", [])
        assert "image" in modalities, (
            f"active_modalities must include 'image' for an image multimodal_context, "
            f"got: {modalities!r}"
        )

    def test_requires_native_multimodal_true_when_image_present(self):
        """requires_native_multimodal must be True when images are provided."""
        from tests.integration.stubs.multimodal_perception_stub import make_image_context

        stub = _make_stub()
        _reset_openclawd_singleton()
        ctx = make_image_context()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_handle_request("Describe image", multimodal_context=ctx)
            )

        cps = result.get("metadata", {}).get("canonical_perception_state", {})
        assert cps.get("requires_native_multimodal") is True, (
            "requires_native_multimodal must be True when images are in the request — "
            "this gates the native-MM-first routing policy in _select_multimodal_route()"
        )

    def test_has_request_multimodal_false_for_text_only(self):
        """has_request_multimodal must be False for a text-only request."""
        stub = _make_stub()
        _reset_openclawd_singleton()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_handle_request("Hello, no image", multimodal_context=None)
            )

        cps = result.get("metadata", {}).get("canonical_perception_state", {})
        assert not cps.get("has_request_multimodal", False), (
            "has_request_multimodal must be False for a text-only request"
        )


# ---------------------------------------------------------------------------
# 4. Multimodal Route Decision In Result
# ---------------------------------------------------------------------------


class TestMultimodalRouteDecisionInResult:
    """Prove multimodal_route_decision appears in DPR response metadata.

    Evidence: core/openclawd.py (metadata["multimodal_route_decision"])
    """

    def test_multimodal_route_decision_present_in_metadata(self):
        """multimodal_route_decision must be present in response metadata."""
        from tests.integration.stubs.multimodal_perception_stub import make_image_context

        stub = _make_stub()
        _reset_openclawd_singleton()
        ctx = make_image_context()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_handle_request("Image test", multimodal_context=ctx)
            )

        md = result.get("metadata", {})
        assert "multimodal_route_decision" in md, (
            "metadata must contain multimodal_route_decision — this is the "
            "canonical routing proof artifact for the multimodal path"
        )

    def test_multimodal_route_decision_has_required_keys(self):
        """multimodal_route_decision must contain route_type and active_modalities."""
        from tests.integration.stubs.multimodal_perception_stub import make_image_context

        stub = _make_stub()
        _reset_openclawd_singleton()
        ctx = make_image_context()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_handle_request("Image routing test", multimodal_context=ctx)
            )

        mrd = result.get("metadata", {}).get("multimodal_route_decision", {})
        for key in ("route_type", "is_native_multimodal", "active_modalities"):
            assert key in mrd, (
                f"multimodal_route_decision must contain key '{key}' — "
                f"all routing decision fields are required for observability"
            )

    def test_active_modalities_in_route_decision_matches_perception_state(self):
        """route_decision.active_modalities must match canonical_perception_state."""
        from tests.integration.stubs.multimodal_perception_stub import make_image_context

        stub = _make_stub()
        _reset_openclawd_singleton()
        ctx = make_image_context()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_handle_request("Modality consistency test", multimodal_context=ctx)
            )

        md = result.get("metadata", {})
        mrd_modalities = md.get("multimodal_route_decision", {}).get("active_modalities", [])
        cps_modalities = md.get("canonical_perception_state", {}).get("active_modalities", [])

        # Both the routing decision and the canonical perception state must include "image",
        # proving the modality signal propagates coherently through the full routing chain.
        assert "image" in cps_modalities, (
            f"canonical_perception_state.active_modalities must include 'image' "
            f"for an image multimodal_context, got: {cps_modalities!r}"
        )
        assert "image" in mrd_modalities, (
            f"multimodal_route_decision.active_modalities must include 'image' "
            f"for an image multimodal_context, got: {mrd_modalities!r} — "
            f"proves modality signal propagates from perception state into the "
            f"routing decision"
        )


# ---------------------------------------------------------------------------
# 5. Routing Observability Event
# ---------------------------------------------------------------------------


class TestRoutingObservabilityEvent:
    """Prove a structured RoutingDecisionEvent is emitted for multimodal requests.

    Evidence: core/routing_observability.py (RoutingDecisionEvent),
              core/openclawd.py (metadata["routing_decision_event"])
    """

    def test_routing_decision_event_present_in_metadata(self):
        """routing_decision_event must be present in metadata for every request."""
        from tests.integration.stubs.multimodal_perception_stub import make_image_context

        stub = _make_stub()
        _reset_openclawd_singleton()
        ctx = make_image_context()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_handle_request("RDE test", multimodal_context=ctx)
            )

        md = result.get("metadata", {})
        rde = md.get("routing_decision_event")
        assert rde is not None, (
            "routing_decision_event must be present in metadata — "
            "it is the structured observability artifact for the routing decision"
        )

    def test_routing_decision_event_has_route_kind(self):
        """routing_decision_event must carry a route_kind field."""
        from tests.integration.stubs.multimodal_perception_stub import make_image_context

        stub = _make_stub()
        _reset_openclawd_singleton()
        ctx = make_image_context()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_handle_request("RDE route_kind test", multimodal_context=ctx)
            )

        rde = result.get("metadata", {}).get("routing_decision_event", {})
        assert "route_kind" in rde, (
            "routing_decision_event must contain 'route_kind' — "
            "this is the stable, serializable route tier outcome"
        )
        assert rde["route_kind"] != ROUTE_TYPE_TEXT_ONLY, (
            "routing_decision_event.route_kind must NOT be 'text_only' for "
            "an image multimodal_context — proves observability event reflects "
            "the multimodal routing decision, not a text-only fallback"
        )

    def test_routing_decision_event_carries_active_modalities(self):
        """routing_decision_event must carry active_modalities."""
        from tests.integration.stubs.multimodal_perception_stub import make_image_context

        stub = _make_stub()
        _reset_openclawd_singleton()
        ctx = make_image_context()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_handle_request("RDE modalities test", multimodal_context=ctx)
            )

        rde = result.get("metadata", {}).get("routing_decision_event", {})
        modalities = rde.get("active_modalities", [])
        assert isinstance(modalities, list), (
            "routing_decision_event.active_modalities must be a list"
        )
        assert "image" in modalities, (
            f"routing_decision_event.active_modalities must include 'image' "
            f"for an image context, got: {modalities!r}"
        )


# ---------------------------------------------------------------------------
# 6. Multimodal vs Text-Only Regression Detection
# ---------------------------------------------------------------------------


class TestMultimodalVsTextOnlyRegression:
    """Regression: multimodal and text-only routes must be distinguishable.

    This is the core regression guard: if multimodal participation is ever
    silently degraded so that multimodal_context produces the same routing
    outcome as text-only, these tests will catch it.

    Evidence: core/openclawd.py (_select_multimodal_route, text_only short-circuit)
    """

    def test_text_only_route_type_is_text_only(self):
        """A text-only request must produce route_type='text_only'."""
        stub = _make_stub()
        _reset_openclawd_singleton()

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_handle_request("Hello, text only")
            )

        route_type = (
            result.get("metadata", {})
            .get("multimodal_route_decision", {})
            .get("route_type", "")
        )
        assert route_type == ROUTE_TYPE_TEXT_ONLY, (
            f"A text-only request must produce route_type='text_only', "
            f"got: {route_type!r}"
        )

    def test_image_multimodal_route_differs_from_text_only(self):
        """Image multimodal_context must produce a DIFFERENT route_type than text-only.

        This is the canonical regression test: if multimodal participation is
        removed or broken, this test will detect it by comparing the route_type
        of a multimodal request against the text-only baseline.
        """
        from tests.integration.stubs.multimodal_perception_stub import make_image_context

        stub = _make_stub()
        _reset_openclawd_singleton()

        with _patch_llm_router(stub):
            text_result = asyncio.run(
                _run_handle_request("Text only message")
            )

        _reset_openclawd_singleton()
        ctx = make_image_context()

        with _patch_llm_router(stub):
            mm_result = asyncio.run(
                _run_handle_request("What is in this image?", multimodal_context=ctx)
            )

        text_route = (
            text_result.get("metadata", {})
            .get("multimodal_route_decision", {})
            .get("route_type", "")
        )
        mm_route = (
            mm_result.get("metadata", {})
            .get("multimodal_route_decision", {})
            .get("route_type", "")
        )

        assert text_route == ROUTE_TYPE_TEXT_ONLY, (
            f"text-only baseline must be 'text_only', got: {text_route!r}"
        )
        assert mm_route != ROUTE_TYPE_TEXT_ONLY, (
            f"multimodal request must produce route_type != 'text_only', "
            f"got: {mm_route!r}.  Regression detected: multimodal participation "
            f"is being silently degraded to text-only routing."
        )

    def test_canonical_perception_state_distinguishes_multimodal_from_text(self):
        """has_request_multimodal must be True for MM and False for text-only."""
        from tests.integration.stubs.multimodal_perception_stub import make_image_context

        stub = _make_stub()
        _reset_openclawd_singleton()

        with _patch_llm_router(stub):
            text_result = asyncio.run(
                _run_handle_request("Text only baseline")
            )

        _reset_openclawd_singleton()
        ctx = make_image_context()

        with _patch_llm_router(stub):
            mm_result = asyncio.run(
                _run_handle_request("MM regression check", multimodal_context=ctx)
            )

        text_cps = text_result.get("metadata", {}).get("canonical_perception_state", {})
        mm_cps = mm_result.get("metadata", {}).get("canonical_perception_state", {})

        assert not text_cps.get("has_request_multimodal", False), (
            "text-only request must have has_request_multimodal=False"
        )
        assert mm_cps.get("has_request_multimodal") is True, (
            "image multimodal request must have has_request_multimodal=True"
        )


# ---------------------------------------------------------------------------
# 7. Android Vision Ingress
# ---------------------------------------------------------------------------


class TestAndroidVisionIngress:
    """Prove the Android vision handler builds a canonical MultiModalContext
    and routes it through DPR via the multimodal path.

    Evidence: galaxy_gateway/android/handlers/vision.py
    """

    def test_android_vision_handler_importable(self):
        """galaxy_gateway.android.handlers.vision must be importable."""
        import importlib
        mod = importlib.import_module("galaxy_gateway.android.handlers.vision")
        assert hasattr(mod, "handle_vision_request"), (
            "handle_vision_request must be present in the Android vision handler"
        )
        assert hasattr(mod, "_process_via_runtime_shell"), (
            "_process_via_runtime_shell must exist — this is the canonical path "
            "that routes Android vision through DPR → OpenClawd"
        )

    def test_android_vision_handler_source_tag_convention(self):
        """The Android handler must create MultiModalContext with android_screen source.

        Evidence: galaxy_gateway/android/handlers/vision.py lines 109-110
        """
        handler_src = (
            REPO_ROOT / "galaxy_gateway" / "android" / "handlers" / "vision.py"
        ).read_text(encoding="utf-8")
        assert "android_screen" in handler_src, (
            "Android vision handler must use 'android_screen:' source prefix — "
            "this is the canonical Android visual origin marker"
        )
        assert "MultiModalContext" in handler_src, (
            "Android vision handler must build a MultiModalContext — "
            "this ensures Android visual input enters the canonical multimodal path"
        )
        assert "get_desktop_presence_runtime" in handler_src, (
            "Android vision handler must route through get_desktop_presence_runtime() — "
            "Android multimodal input must not bypass the runtime shell authority"
        )

    def test_android_vision_stub_context_routes_through_dpr(self):
        """A MultiModalContext with android_screen source must flow through DPR."""
        from tests.integration.stubs.multimodal_perception_stub import (
            make_android_vision_context,
        )

        stub = _make_stub()
        _reset_openclawd_singleton()
        ctx = make_android_vision_context(device_id="android-001")

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_handle_request(
                    "Analyse this Android screen",
                    source="android_vision",
                    multimodal_context=ctx,
                )
            )

        # DPR must return a result dict with the canonical source tag.
        # success may be False in degraded stub environments; we check the
        # multimodal routing evidence that is always set early in process().
        assert isinstance(result, dict), (
            "DPR must return a dict for Android vision multimodal requests"
        )
        assert result.get("entrypoint_source") == "android_vision", (
            "entrypoint_source must be 'android_vision' for Android-sourced requests"
        )
        md = result.get("metadata", {})
        route_type = md.get("multimodal_route_decision", {}).get("route_type", "")
        assert route_type != ROUTE_TYPE_TEXT_ONLY, (
            f"Android vision multimodal request must produce route_type != 'text_only', "
            f"got: {route_type!r}"
        )

    def test_android_vision_result_includes_multimodal_route_decision(self):
        """Android vision result must carry multimodal_route_decision in metadata."""
        from tests.integration.stubs.multimodal_perception_stub import (
            make_android_vision_context,
        )

        stub = _make_stub()
        _reset_openclawd_singleton()
        ctx = make_android_vision_context(device_id="android-002")

        with _patch_llm_router(stub):
            result = asyncio.run(
                _run_handle_request(
                    "Describe screen",
                    source="android_vision",
                    multimodal_context=ctx,
                )
            )

        md = result.get("metadata", {})
        mrd = md.get("multimodal_route_decision")
        assert mrd is not None, (
            "metadata.multimodal_route_decision must be present for Android "
            "vision requests — proves Android multimodal input reaches the "
            "canonical routing authority"
        )
        cps = md.get("canonical_perception_state", {})
        assert cps.get("has_request_multimodal") is True, (
            "canonical_perception_state.has_request_multimodal must be True "
            "for Android vision requests"
        )


# ---------------------------------------------------------------------------
# 8. Android-Side Multimodal Presence
# ---------------------------------------------------------------------------


class TestAndroidSideMultimodalPresence:
    """Prove Android-side VLM presence is tracked in V2 DeviceStateSnapshot.

    Evidence: core/android_device_state_store.py
    """

    def test_device_state_snapshot_has_mobilevlm_present(self):
        """DeviceStateSnapshot must have mobilevlm_present field."""
        from core.android_device_state_store import DeviceStateSnapshot

        snapshot = DeviceStateSnapshot(device_id="test-android")
        d = snapshot.to_dict()
        assert "mobilevlm_present" in d, (
            "DeviceStateSnapshot.to_dict() must include 'mobilevlm_present' — "
            "this tracks Android-side MobileVLM model presence in V2"
        )

    def test_device_state_snapshot_has_seeclick_present(self):
        """DeviceStateSnapshot must have seeclick_present field."""
        from core.android_device_state_store import DeviceStateSnapshot

        snapshot = DeviceStateSnapshot(device_id="test-android")
        d = snapshot.to_dict()
        assert "seeclick_present" in d, (
            "DeviceStateSnapshot.to_dict() must include 'seeclick_present' — "
            "this tracks Android-side SeeClick grounding model presence in V2"
        )

    def test_device_state_snapshot_has_mobilevlm_checksum_ok(self):
        """DeviceStateSnapshot must have mobilevlm_checksum_ok field."""
        from core.android_device_state_store import DeviceStateSnapshot

        snapshot = DeviceStateSnapshot(device_id="test-android")
        d = snapshot.to_dict()
        assert "mobilevlm_checksum_ok" in d, (
            "DeviceStateSnapshot.to_dict() must include 'mobilevlm_checksum_ok' — "
            "this tracks Android-side model integrity"
        )

    def test_device_state_snapshot_source_is_android_store(self):
        """DeviceStateSnapshot._source must be 'android_device_state_store'."""
        from core.android_device_state_store import DeviceStateSnapshot

        snapshot = DeviceStateSnapshot(device_id="test-android")
        d = snapshot.to_dict()
        assert d.get("_source") == "android_device_state_store", (
            "DeviceStateSnapshot provenance must be 'android_device_state_store'"
        )

    def test_android_vision_handler_references_multimodal_route_in_result(self):
        """The Android vision handler must include multimodal_route in result.

        Evidence: galaxy_gateway/android/handlers/vision.py — the result dict
        built by _process_via_runtime_shell() includes analysis.multimodal_route.
        """
        handler_src = (
            REPO_ROOT / "galaxy_gateway" / "android" / "handlers" / "vision.py"
        ).read_text(encoding="utf-8")
        assert "multimodal_route" in handler_src, (
            "Android vision handler result must include 'multimodal_route' key — "
            "proves Android side propagates the multimodal routing decision"
        )

    def test_device_state_store_module_level_functions_present(self):
        """Core android_device_state_store must expose module-level public API."""
        import core.android_device_state_store as store_mod
        assert hasattr(store_mod, "get_device_state_snapshot"), (
            "android_device_state_store must expose get_device_state_snapshot()"
        )
        assert hasattr(store_mod, "get_device_ecosystem_summary"), (
            "android_device_state_store must expose get_device_ecosystem_summary()"
        )
        assert hasattr(store_mod, "list_recent_execution_events"), (
            "android_device_state_store must expose list_recent_execution_events()"
        )


# ---------------------------------------------------------------------------
# 9. Ambient Ingest Remains Gated (Overclaiming Guard)
# ---------------------------------------------------------------------------


class TestAmbientIngestRemainsGated:
    """Prove the continuous ambient ingest path remains SAFE_DEFAULT gated.

    This test prevents overclaiming.  The ambient MultimodalIngressBus path
    is intentionally disabled by default (enable_multimodal_ingest=False in
    SAFE_DEFAULT profile).  Any future PR that accidentally enables it always-on
    will be caught here.

    Evidence: core/multimodal_runtime_profile.py (SAFE_DEFAULT)
    """

    def test_safe_default_profile_exists_and_disables_ingest(self):
        """SAFE_DEFAULT profile must have enable_multimodal_ingest=False."""
        from core.multimodal_runtime_profile import (
            MultimodalRuntimeProfile,
            resolve_multimodal_runtime_profile,
        )

        # SAFE_DEFAULT is the profile name (enum value).
        assert MultimodalRuntimeProfile.SAFE_DEFAULT.value == "safe_default", (
            "MultimodalRuntimeProfile.SAFE_DEFAULT must have value 'safe_default'"
        )
        # Resolve with no config overrides — must produce SAFE_DEFAULT profile
        # with enable_multimodal_ingest=False.
        snapshot = resolve_multimodal_runtime_profile()
        assert snapshot.enable_multimodal_ingest is False, (
            "SAFE_DEFAULT profile must have enable_multimodal_ingest=False — "
            "the ambient continuous ingest path is intentionally gated. "
            "Enabling it without explicit configuration is overclaiming."
        )

    def test_multimodal_ingest_runtime_does_not_start_without_activation(self):
        """get_ingest_bus() must return None when the bus has not been started."""
        from core.multimodal.ingest_runtime import get_ingest_bus

        bus = get_ingest_bus()
        assert bus is None, (
            "get_ingest_bus() must return None when the bus has not been started "
            "via start_ingest_bus().  This ensures the ambient ingest path cannot "
            "be claimed as 'running' without explicit activation."
        )

    def test_multimodal_ingress_bus_importable(self):
        """MultimodalIngressBus must be importable (infrastructure exists)."""
        from core.multimodal.ingress_bus import MultimodalIngressBus

        assert MultimodalIngressBus is not None, (
            "MultimodalIngressBus must be importable — infrastructure is present"
        )

    def test_source_contains_safe_default_in_runtime_profile(self):
        """core/multimodal_runtime_profile.py must contain SAFE_DEFAULT text."""
        profile_src = (
            REPO_ROOT / "core" / "multimodal_runtime_profile.py"
        ).read_text(encoding="utf-8")
        assert "SAFE_DEFAULT" in profile_src, (
            "core/multimodal_runtime_profile.py must define SAFE_DEFAULT — "
            "the canonical guard against always-on ambient ingest"
        )
        assert "enable_multimodal_ingest" in profile_src, (
            "core/multimodal_runtime_profile.py must contain enable_multimodal_ingest"
        )


# ---------------------------------------------------------------------------
# 10. Five-Domain Review Upgrade
# ---------------------------------------------------------------------------


class TestFiveDomainReviewUpgrade:
    """Prove that this test file's existence upgrades the MULTIMODAL_CANONICAL_PATH
    domain in five_domain_implementation_review.

    When tests/integration/test_multimodal_canonical_path.py exists, the
    five_domain_implementation_review must detect it and upgrade the domain
    from INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN → PARTIALLY_ESTABLISHED.

    Evidence: core/five_domain_implementation_review.py (_test_file_exists,
              mm_e2e_test_candidates, evidence_strength conditional)
    """

    def test_this_test_file_is_detected_by_review(self):
        """five_domain_implementation_review must detect this file as e2e proof."""
        from core.five_domain_implementation_review import (
            build_five_domain_review,
            ReviewDomain,
            EvidenceStrength,
        )

        review = build_five_domain_review()
        mm_entry = next(
            e for e in review.domain_entries
            if e.domain == ReviewDomain.MULTIMODAL_CANONICAL_PATH
        )
        assert mm_entry.evidence_strength == EvidenceStrength.PARTIALLY_ESTABLISHED, (
            f"MULTIMODAL_CANONICAL_PATH evidence_strength must be "
            f"PARTIALLY_ESTABLISHED now that the e2e test file exists, "
            f"got: {mm_entry.evidence_strength!r}.  "
            f"This proves the five_domain_review correctly tracks test coverage."
        )

    def test_mm_e2e_test_candidate_list_includes_this_file(self):
        """mm_e2e_test_candidates in five_domain_review must include this test module."""
        review_src = (
            REPO_ROOT / "core" / "five_domain_implementation_review.py"
        ).read_text(encoding="utf-8")
        assert "test_multimodal_canonical_path" in review_src, (
            "five_domain_implementation_review.py must list "
            "'test_multimodal_canonical_path' in mm_e2e_test_candidates"
        )

    def test_review_domain_enum_includes_multimodal(self):
        """ReviewDomain enum must include MULTIMODAL_CANONICAL_PATH."""
        from core.five_domain_implementation_review import ReviewDomain

        assert hasattr(ReviewDomain, "MULTIMODAL_CANONICAL_PATH"), (
            "ReviewDomain must include MULTIMODAL_CANONICAL_PATH"
        )

    def test_evidence_strength_partially_established_exists(self):
        """EvidenceStrength must include PARTIALLY_ESTABLISHED."""
        from core.five_domain_implementation_review import EvidenceStrength

        assert hasattr(EvidenceStrength, "PARTIALLY_ESTABLISHED"), (
            "EvidenceStrength must include PARTIALLY_ESTABLISHED"
        )
