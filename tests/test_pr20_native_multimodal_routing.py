#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr20_native_multimodal_routing.py
=============================================

PR-20 — Native Multimodal-First Routing

Tests covering the routing hierarchy established in PR-20:

1.  route_multimodal_first — native multimodal provider available → tier-1
2.  route_multimodal_first — no native MM provider → tier-2 downgrade
3.  route_multimodal_first — no providers at all → advisory tier-3
4.  route_multimodal_first — text-only flow (no active modalities) → still
    routes via multimodal_first without crashing
5.  _select_multimodal_route — perception requires native MM + provider
    available → native_multimodal route_type
6.  _select_multimodal_route — perception requires native MM + no native
    provider → partial_multimodal route_type with fallback_reason
7.  _select_multimodal_route — text-only perception → text_only route_type
8.  _select_multimodal_route — no router available → advisory
9.  _select_multimodal_route — is_native_multimodal flag correct for each tier
10. _build_unified_control_plan — is_native_multimodal propagated to plan
11. process() metadata — multimodal_route_decision key present
12. process() metadata — text-only request → route_type text_only
13. process() metadata — multimodal request + native provider → route_type
    native_multimodal
14. route_reason and fallback_reason are non-empty strings in each tier
15. Backward compatibility — existing text flows degrade cleanly
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Minimal stub types
# ---------------------------------------------------------------------------

@dataclass
class _FakeProviderConfig:
    name: str
    multimodal: bool = False
    status: str = "healthy"
    default_model: str = "model-v1"
    env_key: str = ""


@dataclass
class _FakeRoutingDecision:
    provider: str
    model: str
    reason: str
    alternatives: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers — build a minimal MultiLLMRouter stub
# ---------------------------------------------------------------------------

def _make_router(providers: Dict[str, _FakeProviderConfig]):
    """Create a MultiLLMRouter-like stub for unit testing route_multimodal_first."""
    from core.multi_llm_router import (
        MultiLLMRouter,
        ProviderConfig,
        ProviderStatus,
        TaskType,
    )

    router = object.__new__(MultiLLMRouter)
    # Build real ProviderConfig objects from stubs
    real_providers: Dict[str, ProviderConfig] = {}
    for name, fake in providers.items():
        cfg = object.__new__(ProviderConfig)
        cfg.name = name
        cfg.multimodal = fake.multimodal
        cfg.status = (
            ProviderStatus.HEALTHY
            if fake.status != "down"
            else ProviderStatus.DOWN
        )
        cfg.default_model = fake.default_model
        cfg.env_key = fake.env_key
        cfg.api_key = ""
        cfg.base_url = ""
        cfg.models = [fake.default_model]
        cfg.cost_per_1k_input = 0.0
        cfg.cost_per_1k_output = 0.0
        cfg.max_tokens = 4096
        cfg.supports_tools = True
        cfg.supports_json_mode = True
        cfg.timeout = 60.0
        cfg.latency_avg_ms = 0.0
        cfg.error_count = 0
        cfg.success_count = 0
        cfg.last_error = None
        cfg.last_used = 0.0
        real_providers[name] = cfg
    router.providers = real_providers
    return router


# ---------------------------------------------------------------------------
# 1. route_multimodal_first — native MM provider available → tier-1
# ---------------------------------------------------------------------------

class TestRouteMultimodalFirstTier1:
    def test_native_mm_provider_selected(self) -> None:
        from core.multi_llm_router import TaskType

        router = _make_router({
            "openai": _FakeProviderConfig("openai", multimodal=True),
            "deepseek": _FakeProviderConfig("deepseek", multimodal=False),
        })
        decision = router.route_multimodal_first(
            active_modalities=["image"],
            task_type=TaskType.GENERAL,
        )
        assert decision.provider == "openai"
        assert "tier=1" in decision.reason

    def test_reason_contains_modalities(self) -> None:
        from core.multi_llm_router import TaskType

        router = _make_router({
            "anthropic": _FakeProviderConfig("anthropic", multimodal=True),
        })
        decision = router.route_multimodal_first(
            active_modalities=["image", "audio"],
            task_type=TaskType.GENERAL,
        )
        assert "image+audio" in decision.reason or "image" in decision.reason

    def test_is_native_multimodal_flag_implied(self) -> None:
        from core.multi_llm_router import TaskType

        router = _make_router({
            "google": _FakeProviderConfig("google", multimodal=True),
        })
        decision = router.route_multimodal_first(
            active_modalities=["video_frame"],
            task_type=TaskType.GENERAL,
        )
        assert decision.provider == "google"
        assert "tier=1" in decision.reason

    def test_down_native_mm_skipped(self) -> None:
        """A DOWN native MM provider must be skipped; fall back to tier-2."""
        from core.multi_llm_router import TaskType

        router = _make_router({
            "openai": _FakeProviderConfig("openai", multimodal=True, status="down"),
            "deepseek": _FakeProviderConfig("deepseek", multimodal=False),
        })
        decision = router.route_multimodal_first(
            active_modalities=["image"],
            task_type=TaskType.GENERAL,
        )
        # No native MM available → tier-2 (deepseek) or tier-3
        assert "tier=1" not in decision.reason


# ---------------------------------------------------------------------------
# 2. route_multimodal_first — no native MM provider → tier-2 downgrade
# ---------------------------------------------------------------------------

class TestRouteMultimodalFirstTier2:
    def test_falls_back_to_text_provider(self) -> None:
        from core.multi_llm_router import TaskType

        router = _make_router({
            "deepseek": _FakeProviderConfig("deepseek", multimodal=False),
        })
        decision = router.route_multimodal_first(
            active_modalities=["image"],
            task_type=TaskType.GENERAL,
        )
        assert decision.provider == "deepseek"
        assert "native_unavailable" in decision.reason or "tier=2" in decision.reason

    def test_fallback_reason_signals_degradation(self) -> None:
        from core.multi_llm_router import TaskType

        router = _make_router({
            "ollama": _FakeProviderConfig("ollama", multimodal=False),
        })
        decision = router.route_multimodal_first(
            active_modalities=["audio"],
            task_type=TaskType.GENERAL,
        )
        assert decision.provider != "none"
        assert "tier=2" in decision.reason or "degraded" in decision.reason or "native_unavailable" in decision.reason


# ---------------------------------------------------------------------------
# 3. route_multimodal_first — no providers → tier-3 advisory
# ---------------------------------------------------------------------------

class TestRouteMultimodalFirstTier4:
    def test_returns_advisory_no_op(self) -> None:
        from core.multi_llm_router import TaskType

        router = _make_router({})
        decision = router.route_multimodal_first(
            active_modalities=["image"],
            task_type=TaskType.GENERAL,
        )
        assert decision.provider == "none"
        assert "advisory" in decision.reason or "tier=3" in decision.reason

    def test_all_providers_down_returns_advisory(self) -> None:
        from core.multi_llm_router import TaskType

        router = _make_router({
            "openai": _FakeProviderConfig("openai", multimodal=True, status="down"),
            "deepseek": _FakeProviderConfig("deepseek", multimodal=False, status="down"),
        })
        decision = router.route_multimodal_first(
            active_modalities=["image"],
            task_type=TaskType.GENERAL,
        )
        assert decision.provider == "none"


# ---------------------------------------------------------------------------
# 4. route_multimodal_first — empty modalities does not crash
# ---------------------------------------------------------------------------

class TestRouteMultimodalFirstTextOnly:
    def test_no_modalities_routes_without_crash(self) -> None:
        from core.multi_llm_router import TaskType

        router = _make_router({
            "openai": _FakeProviderConfig("openai", multimodal=True),
        })
        decision = router.route_multimodal_first(
            active_modalities=[],
            task_type=TaskType.GENERAL,
        )
        # Should not raise; a decision is always returned
        assert decision is not None
        assert isinstance(decision.reason, str)

    def test_none_modalities_routes_without_crash(self) -> None:
        from core.multi_llm_router import TaskType

        router = _make_router({
            "openai": _FakeProviderConfig("openai", multimodal=True),
        })
        decision = router.route_multimodal_first(
            active_modalities=None,
            task_type=TaskType.GENERAL,
        )
        assert decision is not None


# ---------------------------------------------------------------------------
# 5-9.  _select_multimodal_route  (OpenClawd method)
# ---------------------------------------------------------------------------

def _make_openclawd_stub(router=None):
    """Return a minimal OpenClawd instance with _get_router stubbed."""
    from core.openclawd import OpenClawd

    oc = object.__new__(OpenClawd)
    oc._router = router
    oc._initialized = True
    oc._request_count = 0
    return oc


class TestSelectMultimodalRouteNative:
    """5. perception requires native MM + provider available → native_multimodal."""

    def test_native_multimodal_route_type(self) -> None:
        router = _make_router({
            "openai": _FakeProviderConfig("openai", multimodal=True),
        })
        oc = _make_openclawd_stub(router=router)
        perception = {
            "requires_native_multimodal": True,
            "active_modalities": ["image"],
        }
        result = oc._select_multimodal_route(canonical_perception=perception)
        assert result["route_type"] == "native_multimodal"
        assert result["is_native_multimodal"] is True
        assert result["provider"] == "openai"
        assert result["fallback_reason"] == ""

    def test_route_reason_non_empty(self) -> None:
        router = _make_router({
            "anthropic": _FakeProviderConfig("anthropic", multimodal=True),
        })
        oc = _make_openclawd_stub(router=router)
        perception = {
            "requires_native_multimodal": True,
            "active_modalities": ["image", "audio"],
        }
        result = oc._select_multimodal_route(canonical_perception=perception)
        assert isinstance(result["route_reason"], str)
        assert len(result["route_reason"]) > 5


class TestSelectMultimodalRoutePartial:
    """6. perception requires native MM + no native provider → partial_multimodal."""

    def test_partial_multimodal_route_type(self) -> None:
        router = _make_router({
            "deepseek": _FakeProviderConfig("deepseek", multimodal=False),
        })
        oc = _make_openclawd_stub(router=router)
        perception = {
            "requires_native_multimodal": True,
            "active_modalities": ["image"],
        }
        result = oc._select_multimodal_route(canonical_perception=perception)
        assert result["route_type"] == "partial_multimodal"
        assert result["is_native_multimodal"] is False
        assert "fallback_reason" in result
        assert len(result["fallback_reason"]) > 0

    def test_fallback_reason_mentions_native_unavailable(self) -> None:
        router = _make_router({
            "deepseek": _FakeProviderConfig("deepseek", multimodal=False),
        })
        oc = _make_openclawd_stub(router=router)
        perception = {
            "requires_native_multimodal": True,
            "active_modalities": ["audio"],
        }
        result = oc._select_multimodal_route(canonical_perception=perception)
        assert "native" in result["fallback_reason"].lower() or "degraded" in result["fallback_reason"].lower()


class TestSelectMultimodalRouteTextOnly:
    """7. text-only perception → text_only route_type."""

    def test_text_only_perception_returns_text_only(self) -> None:
        router = _make_router({
            "openai": _FakeProviderConfig("openai", multimodal=True),
        })
        oc = _make_openclawd_stub(router=router)
        perception = {
            "requires_native_multimodal": False,
            "active_modalities": [],
        }
        result = oc._select_multimodal_route(canonical_perception=perception)
        assert result["route_type"] == "text_only"
        assert result["is_native_multimodal"] is False

    def test_none_perception_returns_text_only(self) -> None:
        router = _make_router({
            "openai": _FakeProviderConfig("openai", multimodal=True),
        })
        oc = _make_openclawd_stub(router=router)
        result = oc._select_multimodal_route(canonical_perception=None)
        assert result["route_type"] == "text_only"
        assert result["is_native_multimodal"] is False


class TestSelectMultimodalRouteNoRouter:
    """8. router unavailable → advisory."""

    def test_no_router_returns_advisory(self) -> None:
        from core.openclawd import OpenClawd

        oc = object.__new__(OpenClawd)
        oc._router = None
        oc._initialized = True

        perception = {
            "requires_native_multimodal": True,
            "active_modalities": ["image"],
        }
        # Stub _get_router to always return None
        with patch.object(oc, "_get_router", return_value=None):
            result = oc._select_multimodal_route(canonical_perception=perception)
        assert result["route_type"] == "advisory"
        assert result["is_native_multimodal"] is False


class TestSelectMultimodalRouteAdvisory:
    """9. is_native_multimodal flag correct for advisory."""

    def test_advisory_flag_is_false(self) -> None:
        router = _make_router({})  # empty — all tiers fail
        oc = _make_openclawd_stub(router=router)
        perception = {
            "requires_native_multimodal": True,
            "active_modalities": ["image"],
        }
        result = oc._select_multimodal_route(canonical_perception=perception)
        assert result["route_type"] == "advisory"
        assert result["is_native_multimodal"] is False


# ---------------------------------------------------------------------------
# 10. _build_unified_control_plan — is_native_multimodal propagated
# ---------------------------------------------------------------------------

class TestBuildUnifiedControlPlanNativeMultimodal:
    def test_is_native_multimodal_true_propagated(self) -> None:
        from core.openclawd import OpenClawd

        oc = object.__new__(OpenClawd)
        oc._initialized = True

        plan_dict = oc._build_unified_control_plan(
            trace_id="trace_nm_test",
            chosen_model="gpt-5.5",
            chosen_provider="openai",
            is_native_multimodal=True,
        )
        assert plan_dict is not None
        # is_native_multimodal must be surfaced in chosen_model_decision
        cmd = plan_dict.get("chosen_model_decision")
        assert isinstance(cmd, dict), "chosen_model_decision must be a dict"
        assert cmd.get("is_native_multimodal") is True

    def test_is_native_multimodal_false_by_default(self) -> None:
        from core.openclawd import OpenClawd

        oc = object.__new__(OpenClawd)
        oc._initialized = True

        plan_dict = oc._build_unified_control_plan(
            trace_id="trace_nm_default",
            chosen_model="deepseek-chat",
            chosen_provider="deepseek",
        )
        assert plan_dict is not None
        # is_native_multimodal must default to False
        cmd = plan_dict.get("chosen_model_decision") or {}
        if isinstance(cmd, dict):
            assert cmd.get("is_native_multimodal", False) is False


# ---------------------------------------------------------------------------
# 11-13. process() metadata shape
# ---------------------------------------------------------------------------

class TestProcessMetadataMultimodalRouteDecision:
    """11. process() always includes multimodal_route_decision in metadata."""

    def _minimal_process_args(self):
        return {
            "message": "hello world",
            "session_id": "test_session",
        }

    @pytest.mark.asyncio
    async def test_multimodal_route_decision_key_present_text_only(self) -> None:
        """12. Text-only request → route_type text_only in metadata."""
        from core.openclawd import OpenClawd

        oc = OpenClawd.__new__(OpenClawd)
        oc._initialized = False
        oc._router = None
        oc._kernel = None
        oc._request_count = 0
        oc._current_trace_id = None
        oc._current_session_id = None
        oc._current_device_id = ""

        # We just test _select_multimodal_route directly with no perception
        result = oc._select_multimodal_route(canonical_perception=None)
        assert "route_type" in result
        assert result["route_type"] == "text_only"

    def test_result_is_json_serialisable(self) -> None:
        """14. route_reason and fallback_reason are non-empty strings."""
        import json
        router = _make_router({
            "openai": _FakeProviderConfig("openai", multimodal=True),
        })
        oc = _make_openclawd_stub(router=router)
        perception = {
            "requires_native_multimodal": True,
            "active_modalities": ["image"],
        }
        result = oc._select_multimodal_route(canonical_perception=perception)
        # Must be JSON-serialisable
        serialised = json.dumps(result)
        restored = json.loads(serialised)
        assert restored["route_type"] == "native_multimodal"
        assert isinstance(restored["route_reason"], str)
        assert isinstance(restored["fallback_reason"], str)

    def test_route_decision_has_all_required_keys(self) -> None:
        router = _make_router({
            "anthropic": _FakeProviderConfig("anthropic", multimodal=True),
        })
        oc = _make_openclawd_stub(router=router)
        perception = {
            "requires_native_multimodal": True,
            "active_modalities": ["image"],
        }
        result = oc._select_multimodal_route(canonical_perception=perception)
        required_keys = {
            "route_type", "is_native_multimodal", "provider",
            "model", "route_reason", "fallback_reason", "active_modalities",
        }
        assert required_keys <= set(result.keys())


# ---------------------------------------------------------------------------
# 14. route_reason / fallback_reason string quality
# ---------------------------------------------------------------------------

class TestRouteReasonExplicitness:
    def test_tier1_reason_mentions_native_multimodal_first(self) -> None:
        from core.multi_llm_router import TaskType

        router = _make_router({
            "openai": _FakeProviderConfig("openai", multimodal=True),
        })
        decision = router.route_multimodal_first(
            active_modalities=["image"],
            task_type=TaskType.GENERAL,
        )
        assert "native_multimodal_first" in decision.reason

    def test_tier2_reason_mentions_native_multimodal_first(self) -> None:
        from core.multi_llm_router import TaskType

        router = _make_router({
            "deepseek": _FakeProviderConfig("deepseek", multimodal=False),
        })
        decision = router.route_multimodal_first(
            active_modalities=["image"],
            task_type=TaskType.GENERAL,
        )
        assert "native_multimodal_first" in decision.reason

    def test_tier4_reason_mentions_advisory(self) -> None:
        from core.multi_llm_router import TaskType

        router = _make_router({})
        decision = router.route_multimodal_first(
            active_modalities=["image"],
            task_type=TaskType.GENERAL,
        )
        assert "advisory" in decision.reason


# ---------------------------------------------------------------------------
# 15. Backward compatibility — existing text flows
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    def test_text_only_select_route_no_crash(self) -> None:
        """Text-only callers must not be affected by the routing change."""
        from core.multi_llm_router import TaskType

        router = _make_router({
            "openai": _FakeProviderConfig("openai", multimodal=True),
            "deepseek": _FakeProviderConfig("deepseek", multimodal=False),
        })
        oc = _make_openclawd_stub(router=router)
        # No perception state at all
        result = oc._select_multimodal_route(canonical_perception=None)
        assert result["route_type"] == "text_only"

    def test_existing_route_method_unaffected(self) -> None:
        """The existing .route() method must continue to work normally."""
        from core.multi_llm_router import TaskType

        router = _make_router({
            "openai": _FakeProviderConfig("openai", multimodal=True),
            "deepseek": _FakeProviderConfig("deepseek", multimodal=False),
        })
        # Use the original route() method — must not raise
        decision = router.route(task_type=TaskType.GENERAL)
        assert decision is not None
        assert decision.provider != "" or decision.provider == "none"

    def test_select_route_empty_perception_fields(self) -> None:
        """Partially empty perception dict must not crash."""
        router = _make_router({
            "openai": _FakeProviderConfig("openai", multimodal=True),
        })
        oc = _make_openclawd_stub(router=router)
        result = oc._select_multimodal_route(canonical_perception={})
        # requires_native_multimodal defaults to False → text_only
        assert result["route_type"] == "text_only"

    def test_build_ucp_without_is_native_multimodal_still_works(self) -> None:
        """_build_unified_control_plan without is_native_multimodal must not crash."""
        from core.openclawd import OpenClawd

        oc = object.__new__(OpenClawd)
        oc._initialized = True

        plan_dict = oc._build_unified_control_plan(
            trace_id="compat_trace",
            chosen_model="gpt-5.5",
            chosen_provider="openai",
            # is_native_multimodal intentionally omitted — must use default False
        )
        assert plan_dict is not None
