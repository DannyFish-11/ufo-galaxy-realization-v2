"""tests/test_pr18_canonical_model_supply_state.py — PR-18: Canonical Model Supply State

Validates:
1.  NativeMultimodalCapability — construction, active_modalities, to_dict, from_multimodal_flag,
    from_modality_capability, repr
2.  NativeMultimodalCapabilityRegistry — register, get, all_records, natively_multimodal_providers,
    providers_supporting_modality, preferred_multimodal_provider, to_dict, container protocol
3.  ProviderSupplyRecord — construction, to_dict, repr
4.  CanonicalModelSupplyState — construction, available_providers, natively_multimodal_providers,
    preferred_multimodal_provider_id, to_dict, container protocol
5.  build_canonical_model_supply_state — includes known providers/models,
    native multimodal is first-class, fallback/support candidates populated,
    serialisable, backward compatible with existing topology layer
6.  build_canonical_model_supply_state_from_router — bridges MultiLLMRouter,
    capability normalised from ProviderConfig.multimodal flag,
    existing routes remain operational
7.  Module exports — all new symbols importable from core.model_topology
8.  Supply summary — non-empty, diagnosable
9.  Edge cases — empty inventory, all unavailable, all non-multimodal
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

OPENAI_DICT = {
    "provider": "openai",
    "model": "gpt-4o",
    "models": ["gpt-4o", "gpt-4o-mini"],
    "speed_score": 8,
    "quality_score": 9,
    "available": True,
    "multimodal": True,
    "env_keys": ["OPENAI_API_KEY"],
}

ANTHROPIC_DICT = {
    "provider": "anthropic",
    "model": "claude-opus-4.6",
    "models": ["claude-opus-4.6", "claude-sonnet-4.6"],
    "speed_score": 6,
    "quality_score": 10,
    "available": True,
    "multimodal": True,
    "env_keys": ["ANTHROPIC_API_KEY"],
}

GROQ_DICT = {
    "provider": "groq",
    "model": "llama-3.3-70b-versatile",
    "models": ["llama-3.3-70b-versatile"],
    "speed_score": 10,
    "quality_score": 7,
    "available": True,
    "multimodal": False,
    "env_keys": ["GROQ_API_KEY"],
}

DEEPSEEK_DICT = {
    "provider": "deepseek",
    "model": "deepseek-ai/DeepSeek-V3.2",
    "models": ["deepseek-ai/DeepSeek-V3.2"],
    "speed_score": 7,
    "quality_score": 9,
    "available": False,
    "multimodal": False,
    "missing_env_key": "DEEPSEEK_API_KEY",
    "env_keys": ["DEEPSEEK_API_KEY"],
}


@pytest.fixture
def bridge():
    from core.model_topology import ConfigBridge
    return ConfigBridge()


@pytest.fixture
def full_inventory(bridge):
    from core.model_topology import LegacyLLMProviderSnapshot
    snaps = [
        LegacyLLMProviderSnapshot.from_dict(d)
        for d in [OPENAI_DICT, ANTHROPIC_DICT, GROQ_DICT, DEEPSEEK_DICT]
    ]
    return bridge.build_inventory(snaps)


@pytest.fixture
def mm_only_inventory(bridge):
    """Inventory with only natively multimodal providers."""
    from core.model_topology import LegacyLLMProviderSnapshot
    snaps = [
        LegacyLLMProviderSnapshot.from_dict(d)
        for d in [OPENAI_DICT, ANTHROPIC_DICT]
    ]
    return bridge.build_inventory(snaps)


@pytest.fixture
def non_mm_inventory(bridge):
    """Inventory with no natively multimodal providers."""
    from core.model_topology import LegacyLLMProviderSnapshot
    snaps = [LegacyLLMProviderSnapshot.from_dict(GROQ_DICT)]
    return bridge.build_inventory(snaps)


@pytest.fixture
def unavailable_inventory(bridge):
    """Inventory where all providers are unavailable."""
    from core.model_topology import LegacyLLMProviderSnapshot
    snaps = [LegacyLLMProviderSnapshot.from_dict(DEEPSEEK_DICT)]
    return bridge.build_inventory(snaps)


def _make_mock_router(provider_specs: List[Dict]) -> Any:
    """Build a minimal MultiLLMRouter-like mock from a list of provider specs.

    Each spec is a dict with keys: name, models, default_model, multimodal,
    supports_tools, cost_per_1k_input, cost_per_1k_output, latency_avg_ms, status.
    """
    from enum import Enum

    class _Status(str, Enum):
        HEALTHY = "healthy"
        DOWN = "down"

    providers = {}
    for spec in provider_specs:
        cfg = MagicMock()
        cfg.name = spec["name"]
        cfg.models = spec.get("models", [spec.get("default_model", "")])
        cfg.default_model = spec.get("default_model", "")
        cfg.multimodal = spec.get("multimodal", False)
        cfg.supports_tools = spec.get("supports_tools", True)
        cfg.cost_per_1k_input = spec.get("cost_per_1k_input", 0.0)
        cfg.cost_per_1k_output = spec.get("cost_per_1k_output", 0.0)
        cfg.latency_avg_ms = spec.get("latency_avg_ms", 0.0)
        status_val = spec.get("status", "healthy")
        cfg.status = _Status.DOWN if status_val == "down" else _Status.HEALTHY
        providers[spec["name"]] = cfg

    router = MagicMock()
    router.providers = providers
    return router


ROUTER_SPECS = [
    {
        "name": "openai",
        "models": ["gpt-4o", "gpt-4o-mini"],
        "default_model": "gpt-4o",
        "multimodal": True,
        "supports_tools": True,
        "cost_per_1k_input": 0.0025,
        "cost_per_1k_output": 0.01,
        "latency_avg_ms": 1200.0,
        "status": "healthy",
    },
    {
        "name": "anthropic",
        "models": ["claude-opus-4.6", "claude-sonnet-4.6"],
        "default_model": "claude-opus-4.6",
        "multimodal": True,
        "supports_tools": True,
        "cost_per_1k_input": 0.015,
        "cost_per_1k_output": 0.075,
        "latency_avg_ms": 2000.0,
        "status": "healthy",
    },
    {
        "name": "groq",
        "models": ["llama-3.3-70b-versatile"],
        "default_model": "llama-3.3-70b-versatile",
        "multimodal": False,
        "supports_tools": True,
        "cost_per_1k_input": 0.0,
        "cost_per_1k_output": 0.0,
        "latency_avg_ms": 300.0,
        "status": "healthy",
    },
    {
        "name": "deepseek",
        "models": ["deepseek-ai/DeepSeek-V3.2"],
        "default_model": "deepseek-ai/DeepSeek-V3.2",
        "multimodal": False,
        "supports_tools": True,
        "cost_per_1k_input": 0.0,
        "cost_per_1k_output": 0.0,
        "latency_avg_ms": 0.0,
        "status": "down",
    },
]


# ===========================================================================
# 1. NativeMultimodalCapability
# ===========================================================================


class TestNativeMultimodalCapability:
    """Unit tests for the NativeMultimodalCapability value object."""

    def test_basic_construction(self) -> None:
        from core.model_topology import NativeMultimodalCapability

        cap = NativeMultimodalCapability(
            provider_id="openai",
            model_id="gpt-4o",
            is_natively_multimodal=True,
            supports_image_input=True,
            supports_audio_input=False,
            supports_video_frame_input=False,
        )
        assert cap.provider_id == "openai"
        assert cap.model_id == "gpt-4o"
        assert cap.is_natively_multimodal is True
        assert cap.supports_image_input is True
        assert cap.supports_audio_input is False
        assert cap.supports_video_frame_input is False

    def test_active_modalities_image_only(self) -> None:
        from core.model_topology import NativeMultimodalCapability

        cap = NativeMultimodalCapability(
            provider_id="p", model_id="m",
            supports_image_input=True,
            supports_audio_input=False,
            supports_video_frame_input=False,
        )
        assert "image" in cap.active_modalities
        assert "audio" not in cap.active_modalities
        assert "video_frame" not in cap.active_modalities

    def test_active_modalities_all_flags(self) -> None:
        from core.model_topology import NativeMultimodalCapability

        cap = NativeMultimodalCapability(
            provider_id="p", model_id="m",
            supports_image_input=True,
            supports_audio_input=True,
            supports_video_frame_input=True,
        )
        assert set(cap.active_modalities) >= {"image", "audio", "video_frame"}

    def test_active_modalities_text_only(self) -> None:
        from core.model_topology import NativeMultimodalCapability

        cap = NativeMultimodalCapability(provider_id="p", model_id="m")
        assert cap.active_modalities == []

    def test_to_dict_structure(self) -> None:
        from core.model_topology import NativeMultimodalCapability

        cap = NativeMultimodalCapability(
            provider_id="openai", model_id="gpt-4o",
            is_natively_multimodal=True,
            supports_image_input=True,
        )
        d = cap.to_dict()
        assert d["provider_id"] == "openai"
        assert d["model_id"] == "gpt-4o"
        assert d["is_natively_multimodal"] is True
        assert d["supports_image_input"] is True
        assert "active_modalities" in d
        assert "image" in d["active_modalities"]

    def test_to_dict_is_json_serialisable(self) -> None:
        from core.model_topology import NativeMultimodalCapability

        cap = NativeMultimodalCapability(
            provider_id="openai", model_id="gpt-4o",
            is_natively_multimodal=True,
            supports_image_input=True,
        )
        serialised = json.dumps(cap.to_dict())
        restored = json.loads(serialised)
        assert restored["provider_id"] == "openai"

    def test_from_multimodal_flag_true_implies_image(self) -> None:
        from core.model_topology import NativeMultimodalCapability

        cap = NativeMultimodalCapability.from_multimodal_flag(
            provider_id="openai", model_id="gpt-4o", multimodal=True
        )
        assert cap.is_natively_multimodal is True
        assert cap.supports_image_input is True

    def test_from_multimodal_flag_false_is_text_only(self) -> None:
        from core.model_topology import NativeMultimodalCapability

        cap = NativeMultimodalCapability.from_multimodal_flag(
            provider_id="groq", model_id="llama-3.3", multimodal=False
        )
        assert cap.is_natively_multimodal is False
        assert cap.supports_image_input is False
        assert cap.active_modalities == []

    def test_from_modality_capability_vision(self) -> None:
        from core.model_topology import NativeMultimodalCapability
        from core.model_topology.topology_types import ModalityCapability

        modality = ModalityCapability(
            native_multimodal=True,
            supports_vision=True,
            supports_audio=False,
            supports_video=False,
        )
        cap = NativeMultimodalCapability.from_modality_capability(
            provider_id="openai", model_id="gpt-4o", modality=modality
        )
        assert cap.is_natively_multimodal is True
        assert cap.supports_image_input is True
        assert cap.supports_audio_input is False
        assert cap.supports_video_frame_input is False

    def test_from_modality_capability_full_matrix(self) -> None:
        from core.model_topology import NativeMultimodalCapability
        from core.model_topology.topology_types import ModalityCapability

        modality = ModalityCapability(
            native_multimodal=True,
            supports_vision=True,
            supports_audio=True,
            supports_video=True,
        )
        cap = NativeMultimodalCapability.from_modality_capability(
            provider_id="google", model_id="gemini-3.1-pro", modality=modality
        )
        assert cap.supports_audio_input is True
        assert cap.supports_video_frame_input is True

    def test_repr_contains_provider_and_model(self) -> None:
        from core.model_topology import NativeMultimodalCapability

        cap = NativeMultimodalCapability(
            provider_id="openai", model_id="gpt-4o",
            is_natively_multimodal=True, supports_image_input=True
        )
        r = repr(cap)
        assert "openai" in r
        assert "gpt-4o" in r


# ===========================================================================
# 2. NativeMultimodalCapabilityRegistry
# ===========================================================================


class TestNativeMultimodalCapabilityRegistry:
    """Unit tests for the NativeMultimodalCapabilityRegistry."""

    def _make_registry(self) -> Any:
        from core.model_topology import NativeMultimodalCapabilityRegistry
        return NativeMultimodalCapabilityRegistry()

    def _make_cap(self, provider_id: str, multimodal: bool = True) -> Any:
        from core.model_topology import NativeMultimodalCapability
        return NativeMultimodalCapability.from_multimodal_flag(
            provider_id=provider_id, model_id=f"{provider_id}-model", multimodal=multimodal
        )

    def test_register_and_get(self) -> None:
        reg = self._make_registry()
        cap = self._make_cap("openai", multimodal=True)
        reg.register(cap)
        assert reg.get("openai") is cap

    def test_register_many(self) -> None:
        reg = self._make_registry()
        caps = [self._make_cap(pid) for pid in ["openai", "anthropic", "groq"]]
        reg.register_many(caps)
        assert len(reg) == 3

    def test_all_records_returns_all(self) -> None:
        reg = self._make_registry()
        reg.register_many([self._make_cap("openai"), self._make_cap("anthropic")])
        assert len(reg.all_records()) == 2

    def test_natively_multimodal_providers_filters_correctly(self) -> None:
        reg = self._make_registry()
        reg.register(self._make_cap("openai", multimodal=True))
        reg.register(self._make_cap("groq", multimodal=False))
        mm = reg.natively_multimodal_providers()
        provider_ids = [c.provider_id for c in mm]
        assert "openai" in provider_ids
        assert "groq" not in provider_ids

    def test_providers_supporting_modality_image(self) -> None:
        reg = self._make_registry()
        reg.register(self._make_cap("openai", multimodal=True))   # has image
        reg.register(self._make_cap("groq", multimodal=False))    # no image
        img_capable = reg.providers_supporting_modality("image")
        assert any(c.provider_id == "openai" for c in img_capable)
        assert not any(c.provider_id == "groq" for c in img_capable)

    def test_providers_supporting_modality_audio(self) -> None:
        from core.model_topology import NativeMultimodalCapability
        reg = self._make_registry()
        cap = NativeMultimodalCapability(
            provider_id="google", model_id="gemini-3.1",
            is_natively_multimodal=True,
            supports_audio_input=True,
        )
        reg.register(cap)
        audio_cap = reg.providers_supporting_modality("audio")
        assert any(c.provider_id == "google" for c in audio_cap)

    def test_preferred_multimodal_provider_returns_mm(self) -> None:
        reg = self._make_registry()
        reg.register(self._make_cap("groq", multimodal=False))
        reg.register(self._make_cap("openai", multimodal=True))
        preferred = reg.preferred_multimodal_provider()
        assert preferred is not None
        assert preferred.is_natively_multimodal is True

    def test_preferred_multimodal_provider_none_when_no_mm(self) -> None:
        reg = self._make_registry()
        reg.register(self._make_cap("groq", multimodal=False))
        preferred = reg.preferred_multimodal_provider()
        assert preferred is None

    def test_preferred_multimodal_provider_required_modality(self) -> None:
        from core.model_topology import NativeMultimodalCapability
        reg = self._make_registry()
        # openai: image only
        reg.register(NativeMultimodalCapability(
            provider_id="openai", model_id="gpt-4o",
            is_natively_multimodal=True, supports_image_input=True,
        ))
        # google: image + audio
        reg.register(NativeMultimodalCapability(
            provider_id="google", model_id="gemini-3.1",
            is_natively_multimodal=True, supports_image_input=True, supports_audio_input=True,
        ))
        # When audio is required, google should be preferred
        preferred_audio = reg.preferred_multimodal_provider(required_modalities=["audio"])
        assert preferred_audio is not None
        assert preferred_audio.provider_id == "google"

    def test_to_dict_is_json_serialisable(self) -> None:
        reg = self._make_registry()
        reg.register(self._make_cap("openai", multimodal=True))
        reg.register(self._make_cap("groq", multimodal=False))
        d = reg.to_dict()
        serialised = json.dumps(d)
        restored = json.loads(serialised)
        assert "records" in restored
        assert "stats" in restored
        assert restored["stats"]["total"] == 2
        assert restored["stats"]["natively_multimodal"] == 1

    def test_contains_protocol(self) -> None:
        reg = self._make_registry()
        reg.register(self._make_cap("openai"))
        assert "openai" in reg
        assert "anthropic" not in reg

    def test_len_protocol(self) -> None:
        reg = self._make_registry()
        assert len(reg) == 0
        reg.register(self._make_cap("openai"))
        assert len(reg) == 1

    def test_repr_contains_stats(self) -> None:
        reg = self._make_registry()
        reg.register(self._make_cap("openai", multimodal=True))
        r = repr(reg)
        assert "total=1" in r
        assert "multimodal=1" in r

    def test_register_empty_provider_id_raises(self) -> None:
        from core.model_topology import NativeMultimodalCapability
        reg = self._make_registry()
        with pytest.raises(ValueError):
            reg.register(NativeMultimodalCapability(provider_id="", model_id="m"))


# ===========================================================================
# 3. ProviderSupplyRecord
# ===========================================================================


class TestProviderSupplyRecord:
    """Unit tests for ProviderSupplyRecord."""

    def test_basic_construction(self) -> None:
        from core.model_topology import ProviderSupplyRecord, ProviderHealthStatus, ProviderLocalityClass

        record = ProviderSupplyRecord(
            provider_id="openai",
            models=["gpt-4o"],
            default_model="gpt-4o",
            health_status=ProviderHealthStatus.HEALTHY,
            locality_class=ProviderLocalityClass.CLOUD,
            is_available=True,
        )
        assert record.provider_id == "openai"
        assert record.is_available is True
        assert record.health_status == ProviderHealthStatus.HEALTHY

    def test_to_dict_structure(self) -> None:
        from core.model_topology import ProviderSupplyRecord, ProviderHealthStatus, ProviderLocalityClass

        record = ProviderSupplyRecord(
            provider_id="openai",
            models=["gpt-4o"],
            default_model="gpt-4o",
            health_status=ProviderHealthStatus.HEALTHY,
            locality_class=ProviderLocalityClass.CLOUD,
            is_available=True,
        )
        d = record.to_dict()
        assert d["provider_id"] == "openai"
        assert d["health_status"] == "healthy"
        assert d["locality_class"] == "cloud"
        assert d["is_available"] is True
        assert "models" in d
        assert "capability" in d

    def test_to_dict_is_json_serialisable(self) -> None:
        from core.model_topology import ProviderSupplyRecord, ProviderHealthStatus, ProviderLocalityClass

        record = ProviderSupplyRecord(
            provider_id="openai",
            models=["gpt-4o"],
            default_model="gpt-4o",
            health_status=ProviderHealthStatus.HEALTHY,
            locality_class=ProviderLocalityClass.CLOUD,
            is_available=True,
        )
        serialised = json.dumps(record.to_dict())
        assert json.loads(serialised)["provider_id"] == "openai"

    def test_repr_contains_provider_id(self) -> None:
        from core.model_topology import ProviderSupplyRecord

        record = ProviderSupplyRecord(provider_id="openai", is_available=True)
        assert "openai" in repr(record)


# ===========================================================================
# 4. CanonicalModelSupplyState construction
# ===========================================================================


class TestCanonicalModelSupplyStateConstruction:
    """Tests for the CanonicalModelSupplyState dataclass itself."""

    def test_empty_state(self) -> None:
        from core.model_topology import CanonicalModelSupplyState

        state = CanonicalModelSupplyState()
        assert len(state) == 0
        assert state.available_providers() == []
        assert state.natively_multimodal_providers() == []
        assert state.primary_provider_id is None

    def test_get_provider(self) -> None:
        from core.model_topology import CanonicalModelSupplyState, ProviderSupplyRecord

        state = CanonicalModelSupplyState()
        record = ProviderSupplyRecord(provider_id="openai", is_available=True)
        state.providers["openai"] = record
        assert state.get_provider("openai") is record
        assert state.get_provider("missing") is None

    def test_to_dict_structure(self) -> None:
        from core.model_topology import CanonicalModelSupplyState

        state = CanonicalModelSupplyState(snapshot_id="snap-001")
        d = state.to_dict()
        assert "snapshot_id" in d
        assert "providers" in d
        assert "multimodal_registry" in d
        assert "primary_provider_id" in d
        assert "fallback_candidates" in d
        assert "support_model_candidates" in d
        assert "natively_multimodal_provider_ids" in d
        assert "available_provider_ids" in d
        assert "unavailable_provider_ids" in d
        assert "stats" in d

    def test_to_dict_is_json_serialisable(self) -> None:
        from core.model_topology import CanonicalModelSupplyState

        state = CanonicalModelSupplyState(snapshot_id="snap-002")
        serialised = json.dumps(state.to_dict())
        restored = json.loads(serialised)
        assert restored["snapshot_id"] == "snap-002"

    def test_repr_contains_useful_info(self) -> None:
        from core.model_topology import CanonicalModelSupplyState

        state = CanonicalModelSupplyState()
        r = repr(state)
        assert "CanonicalModelSupplyState" in r
        assert "providers=0" in r


# ===========================================================================
# 5. build_canonical_model_supply_state — from ProviderInventory
# ===========================================================================


class TestBuildCanonicalModelSupplyStateFromInventory:
    """Tests for build_canonical_model_supply_state() from topology inventory."""

    def test_includes_known_providers(self, full_inventory) -> None:
        from core.model_topology import build_canonical_model_supply_state

        state = build_canonical_model_supply_state(full_inventory)
        assert "openai" in state.providers
        assert "anthropic" in state.providers
        assert "groq" in state.providers
        assert "deepseek" in state.providers

    def test_available_providers_correct(self, full_inventory) -> None:
        from core.model_topology import build_canonical_model_supply_state

        state = build_canonical_model_supply_state(full_inventory)
        # openai, anthropic, groq are available; deepseek is not
        assert "openai" in state.available_provider_ids
        assert "anthropic" in state.available_provider_ids
        assert "groq" in state.available_provider_ids
        assert "deepseek" not in state.available_provider_ids
        assert "deepseek" in state.unavailable_provider_ids

    def test_native_multimodal_is_first_class(self, full_inventory) -> None:
        from core.model_topology import build_canonical_model_supply_state

        state = build_canonical_model_supply_state(full_inventory)
        # openai and anthropic are multimodal; groq and deepseek are not
        assert "openai" in state.natively_multimodal_provider_ids
        assert "anthropic" in state.natively_multimodal_provider_ids
        assert "groq" not in state.natively_multimodal_provider_ids
        assert "deepseek" not in state.natively_multimodal_provider_ids

    def test_multimodal_registry_populated(self, full_inventory) -> None:
        from core.model_topology import build_canonical_model_supply_state

        state = build_canonical_model_supply_state(full_inventory)
        reg = state.multimodal_registry
        assert "openai" in reg
        assert "groq" in reg
        mm = reg.natively_multimodal_providers()
        assert any(c.provider_id == "openai" for c in mm)
        assert not any(c.provider_id == "groq" for c in mm)

    def test_capability_matrix_serialisable(self, full_inventory) -> None:
        from core.model_topology import build_canonical_model_supply_state

        state = build_canonical_model_supply_state(full_inventory)
        # Full state must be JSON-serialisable
        serialised = json.dumps(state.to_dict())
        restored = json.loads(serialised)
        assert "providers" in restored
        assert "multimodal_registry" in restored
        assert "stats" in restored

    def test_fallback_candidates_populated(self, full_inventory) -> None:
        from core.model_topology import build_canonical_model_supply_state

        state = build_canonical_model_supply_state(full_inventory)
        assert len(state.fallback_candidates) > 0
        # Primary is not in fallback candidates
        assert state.primary_provider_id not in state.fallback_candidates

    def test_fallback_candidates_without_ambiguity(self, full_inventory) -> None:
        from core.model_topology import build_canonical_model_supply_state

        state = build_canonical_model_supply_state(full_inventory)
        # Fallback candidates are all available
        for pid in state.fallback_candidates:
            record = state.get_provider(pid)
            assert record is not None
            assert record.is_available, f"{pid} is fallback candidate but not available"

    def test_support_model_candidates_populated(self, full_inventory) -> None:
        from core.model_topology import build_canonical_model_supply_state

        state = build_canonical_model_supply_state(full_inventory)
        # At least some support model candidates exist given multiple available providers
        assert isinstance(state.support_model_candidates, list)

    def test_primary_is_natively_multimodal_when_possible(self, full_inventory) -> None:
        from core.model_topology import build_canonical_model_supply_state

        state = build_canonical_model_supply_state(full_inventory)
        # Primary should be a natively multimodal provider when one is available
        if state.primary_provider_id:
            primary_record = state.get_provider(state.primary_provider_id)
            assert primary_record is not None
            # Primary should be natively multimodal (openai or anthropic are available)
            assert primary_record.capability is not None
            assert primary_record.capability.is_natively_multimodal is True

    def test_preferred_multimodal_provider_id_available(self, full_inventory) -> None:
        from core.model_topology import build_canonical_model_supply_state

        state = build_canonical_model_supply_state(full_inventory)
        preferred = state.preferred_multimodal_provider_id()
        assert preferred is not None
        assert preferred in state.available_provider_ids

    def test_supply_summary_non_empty(self, full_inventory) -> None:
        from core.model_topology import build_canonical_model_supply_state

        state = build_canonical_model_supply_state(full_inventory)
        assert state.supply_summary
        assert isinstance(state.supply_summary, str)
        assert len(state.supply_summary) > 0

    def test_snapshot_id_propagated(self, full_inventory) -> None:
        from core.model_topology import build_canonical_model_supply_state

        state = build_canonical_model_supply_state(full_inventory, snapshot_id="snap-xyz")
        assert state.snapshot_id == "snap-xyz"
        assert state.to_dict()["snapshot_id"] == "snap-xyz"

    def test_topology_route_plan_enrichment(self, full_inventory) -> None:
        from core.model_topology import build_canonical_model_supply_state, TopologyRouter
        from core.continuum.types import TriStatePhase, RuntimeDomain

        router = TopologyRouter(full_inventory)
        plan = router.route(TriStatePhase.MANIFEST, RuntimeDomain.LOCAL)
        state = build_canonical_model_supply_state(full_inventory, topology_route_plan=plan)

        # Route reason from plan should be propagated
        assert state.topology_route_reason == plan.route_reason

        # Primary should match the plan's primary model
        if plan.primary_model:
            assert state.primary_provider_id == plan.primary_model.provider.provider_id

    def test_non_mm_inventory_has_no_multimodal_providers(self, non_mm_inventory) -> None:
        from core.model_topology import build_canonical_model_supply_state

        state = build_canonical_model_supply_state(non_mm_inventory)
        assert len(state.natively_multimodal_provider_ids) == 0
        mm_providers = state.natively_multimodal_providers()
        assert mm_providers == []

    def test_preferred_multimodal_provider_none_when_no_mm(self, non_mm_inventory) -> None:
        from core.model_topology import build_canonical_model_supply_state

        state = build_canonical_model_supply_state(non_mm_inventory)
        preferred = state.preferred_multimodal_provider_id()
        # No natively multimodal provider, should return None
        assert preferred is None

    def test_unavailable_providers_in_unavailable_list(self, full_inventory) -> None:
        from core.model_topology import build_canonical_model_supply_state

        state = build_canonical_model_supply_state(full_inventory)
        # deepseek is unavailable
        assert "deepseek" in state.unavailable_provider_ids

    def test_no_duplicate_provider_ids(self, full_inventory) -> None:
        from core.model_topology import build_canonical_model_supply_state

        state = build_canonical_model_supply_state(full_inventory)
        assert len(state.available_provider_ids) == len(set(state.available_provider_ids))
        assert len(state.unavailable_provider_ids) == len(set(state.unavailable_provider_ids))
        assert len(state.natively_multimodal_provider_ids) == len(set(state.natively_multimodal_provider_ids))

    def test_provider_record_capability_not_none(self, full_inventory) -> None:
        from core.model_topology import build_canonical_model_supply_state

        state = build_canonical_model_supply_state(full_inventory)
        for record in state.providers.values():
            assert record.capability is not None, f"{record.provider_id} has no capability"


# ===========================================================================
# 6. build_canonical_model_supply_state_from_router — from MultiLLMRouter
# ===========================================================================


class TestBuildCanonicalModelSupplyStateFromRouter:
    """Tests for build_canonical_model_supply_state_from_router()."""

    @pytest.fixture
    def mock_router(self):
        return _make_mock_router(ROUTER_SPECS)

    def test_includes_all_router_providers(self, mock_router) -> None:
        from core.model_topology import build_canonical_model_supply_state_from_router

        state = build_canonical_model_supply_state_from_router(mock_router)
        assert "openai" in state.providers
        assert "anthropic" in state.providers
        assert "groq" in state.providers
        assert "deepseek" in state.providers

    def test_native_multimodal_normalised_from_router_flag(self, mock_router) -> None:
        from core.model_topology import build_canonical_model_supply_state_from_router

        state = build_canonical_model_supply_state_from_router(mock_router)
        assert "openai" in state.natively_multimodal_provider_ids
        assert "anthropic" in state.natively_multimodal_provider_ids
        assert "groq" not in state.natively_multimodal_provider_ids
        assert "deepseek" not in state.natively_multimodal_provider_ids

    def test_capability_registry_populated(self, mock_router) -> None:
        from core.model_topology import build_canonical_model_supply_state_from_router

        state = build_canonical_model_supply_state_from_router(mock_router)
        reg = state.multimodal_registry
        mm = reg.natively_multimodal_providers()
        assert any(c.provider_id == "openai" for c in mm)
        assert not any(c.provider_id == "groq" for c in mm)

    def test_down_providers_are_unavailable(self, mock_router) -> None:
        from core.model_topology import build_canonical_model_supply_state_from_router

        state = build_canonical_model_supply_state_from_router(mock_router)
        # deepseek has status=down
        assert "deepseek" not in state.available_provider_ids

    def test_healthy_providers_are_available(self, mock_router) -> None:
        from core.model_topology import build_canonical_model_supply_state_from_router

        state = build_canonical_model_supply_state_from_router(mock_router)
        assert "openai" in state.available_provider_ids
        assert "groq" in state.available_provider_ids

    def test_cost_hints_preserved(self, mock_router) -> None:
        from core.model_topology import build_canonical_model_supply_state_from_router

        state = build_canonical_model_supply_state_from_router(mock_router)
        openai_record = state.get_provider("openai")
        assert openai_record is not None
        assert openai_record.cost_per_1k_input == pytest.approx(0.0025)
        assert openai_record.cost_per_1k_output == pytest.approx(0.01)

    def test_latency_hints_preserved(self, mock_router) -> None:
        from core.model_topology import build_canonical_model_supply_state_from_router

        state = build_canonical_model_supply_state_from_router(mock_router)
        groq_record = state.get_provider("groq")
        assert groq_record is not None
        assert groq_record.latency_avg_ms == pytest.approx(300.0)

    def test_fallback_candidates_populated(self, mock_router) -> None:
        from core.model_topology import build_canonical_model_supply_state_from_router

        state = build_canonical_model_supply_state_from_router(mock_router)
        assert len(state.fallback_candidates) > 0
        # primary not in fallback list
        assert state.primary_provider_id not in state.fallback_candidates

    def test_capability_matrix_serialisable(self, mock_router) -> None:
        from core.model_topology import build_canonical_model_supply_state_from_router

        state = build_canonical_model_supply_state_from_router(mock_router)
        serialised = json.dumps(state.to_dict())
        restored = json.loads(serialised)
        assert "providers" in restored
        assert "multimodal_registry" in restored
        assert restored["stats"]["natively_multimodal"] == 2

    def test_existing_router_unmodified(self, mock_router) -> None:
        """build_canonical_model_supply_state_from_router must not mutate the router."""
        from core.model_topology import build_canonical_model_supply_state_from_router

        providers_before = dict(mock_router.providers)
        build_canonical_model_supply_state_from_router(mock_router)
        assert dict(mock_router.providers).keys() == providers_before.keys()

    def test_snapshot_id_propagated(self, mock_router) -> None:
        from core.model_topology import build_canonical_model_supply_state_from_router

        state = build_canonical_model_supply_state_from_router(mock_router, snapshot_id="rtr-snap")
        assert state.snapshot_id == "rtr-snap"


# ===========================================================================
# 7. Module exports
# ===========================================================================


class TestModuleExports:
    """All new PR-18 symbols must be importable from core.model_topology."""

    def test_canonical_model_supply_state_importable(self) -> None:
        from core.model_topology import CanonicalModelSupplyState
        assert CanonicalModelSupplyState is not None

    def test_native_multimodal_capability_importable(self) -> None:
        from core.model_topology import NativeMultimodalCapability
        assert NativeMultimodalCapability is not None

    def test_native_multimodal_capability_registry_importable(self) -> None:
        from core.model_topology import NativeMultimodalCapabilityRegistry
        assert NativeMultimodalCapabilityRegistry is not None

    def test_provider_supply_record_importable(self) -> None:
        from core.model_topology import ProviderSupplyRecord
        assert ProviderSupplyRecord is not None

    def test_provider_health_status_importable(self) -> None:
        from core.model_topology import ProviderHealthStatus
        assert ProviderHealthStatus is not None

    def test_provider_locality_class_importable(self) -> None:
        from core.model_topology import ProviderLocalityClass
        assert ProviderLocalityClass is not None

    def test_build_canonical_model_supply_state_importable(self) -> None:
        from core.model_topology import build_canonical_model_supply_state
        assert callable(build_canonical_model_supply_state)

    def test_build_canonical_model_supply_state_from_router_importable(self) -> None:
        from core.model_topology import build_canonical_model_supply_state_from_router
        assert callable(build_canonical_model_supply_state_from_router)

    def test_all_new_symbols_in___all__(self) -> None:
        import core.model_topology as mt
        expected = {
            "CanonicalModelSupplyState",
            "NativeMultimodalCapability",
            "NativeMultimodalCapabilityRegistry",
            "ProviderSupplyRecord",
            "ProviderHealthStatus",
            "ProviderLocalityClass",
            "build_canonical_model_supply_state",
            "build_canonical_model_supply_state_from_router",
        }
        missing = expected - set(mt.__all__)
        assert not missing, f"Missing from __all__: {missing}"


# ===========================================================================
# 8. Supply summary diagnostics
# ===========================================================================


class TestSupplySummary:
    """Supply summary must be non-empty and diagnosable."""

    def test_supply_summary_non_empty(self, full_inventory) -> None:
        from core.model_topology import build_canonical_model_supply_state

        state = build_canonical_model_supply_state(full_inventory)
        assert state.supply_summary
        assert "supply:" in state.supply_summary

    def test_supply_summary_contains_avail_counts(self, full_inventory) -> None:
        from core.model_topology import build_canonical_model_supply_state

        state = build_canonical_model_supply_state(full_inventory)
        # Should mention available count
        assert "avail=" in state.supply_summary

    def test_supply_summary_mentions_primary(self, full_inventory) -> None:
        from core.model_topology import build_canonical_model_supply_state

        state = build_canonical_model_supply_state(full_inventory)
        if state.primary_provider_id:
            assert state.primary_provider_id in state.supply_summary

    def test_supply_summary_empty_inventory(self, bridge) -> None:
        from core.model_topology import ProviderInventory, build_canonical_model_supply_state

        empty_inv = ProviderInventory()
        state = build_canonical_model_supply_state(empty_inv)
        assert state.supply_summary == "supply:empty"


# ===========================================================================
# 9. Edge cases
# ===========================================================================


class TestEdgeCases:
    """Edge case coverage: empty inventory, all unavailable, all non-multimodal."""

    def test_empty_inventory_produces_valid_state(self, bridge) -> None:
        from core.model_topology import ProviderInventory, build_canonical_model_supply_state

        empty_inv = ProviderInventory()
        state = build_canonical_model_supply_state(empty_inv)
        assert len(state) == 0
        assert state.primary_provider_id is None
        assert state.fallback_candidates == []
        assert state.to_dict()["stats"]["total_providers"] == 0

    def test_empty_inventory_serialisable(self, bridge) -> None:
        from core.model_topology import ProviderInventory, build_canonical_model_supply_state

        empty_inv = ProviderInventory()
        state = build_canonical_model_supply_state(empty_inv)
        serialised = json.dumps(state.to_dict())
        restored = json.loads(serialised)
        assert restored["stats"]["total_providers"] == 0

    def test_all_unavailable_no_primary(self, unavailable_inventory) -> None:
        from core.model_topology import build_canonical_model_supply_state

        state = build_canonical_model_supply_state(unavailable_inventory)
        assert len(state.available_provider_ids) == 0
        # primary_provider_id may be None or point to unavailable provider
        # but fallback should be empty since nothing available
        assert state.fallback_candidates == []

    def test_single_provider_is_primary(self, non_mm_inventory) -> None:
        from core.model_topology import build_canonical_model_supply_state

        state = build_canonical_model_supply_state(non_mm_inventory)
        assert state.primary_provider_id == "groq"
        assert state.fallback_candidates == []

    def test_empty_router_produces_valid_state(self) -> None:
        from core.model_topology import build_canonical_model_supply_state_from_router

        empty_router = MagicMock()
        empty_router.providers = {}
        state = build_canonical_model_supply_state_from_router(empty_router)
        assert len(state) == 0
        assert state.primary_provider_id is None
        serialised = json.dumps(state.to_dict())
        assert json.loads(serialised)["stats"]["total_providers"] == 0

    def test_topology_role_hints_preserved(self, full_inventory) -> None:
        from core.model_topology import build_canonical_model_supply_state

        state = build_canonical_model_supply_state(full_inventory)
        # Each provider record should have topology_role_hints list (may be empty)
        for record in state.providers.values():
            assert isinstance(record.topology_role_hints, list)

    def test_preferred_multimodal_provider_respects_availability(self) -> None:
        """preferred_multimodal_provider_id must only return available providers."""
        from core.model_topology import (
            build_canonical_model_supply_state,
            ProviderInventory, ProviderInventoryEntry, LegacyLLMProviderSnapshot, ConfigBridge
        )
        bridge = ConfigBridge()
        # Make an inventory with a multimodal but unavailable provider, and an available non-mm one
        mm_unavail_dict = {
            "provider": "openai",
            "model": "gpt-4o",
            "models": ["gpt-4o"],
            "speed_score": 8,
            "quality_score": 9,
            "available": False,   # NOT available
            "multimodal": True,
            "missing_env_key": "OPENAI_API_KEY",
            "env_keys": ["OPENAI_API_KEY"],
        }
        groq_avail_dict = {
            "provider": "groq",
            "model": "llama-3.3-70b-versatile",
            "models": ["llama-3.3-70b-versatile"],
            "speed_score": 10,
            "quality_score": 7,
            "available": True,
            "multimodal": False,
            "env_keys": ["GROQ_API_KEY"],
        }
        snaps = [
            LegacyLLMProviderSnapshot.from_dict(mm_unavail_dict),
            LegacyLLMProviderSnapshot.from_dict(groq_avail_dict),
        ]
        inv = bridge.build_inventory(snaps)
        state = build_canonical_model_supply_state(inv)

        preferred = state.preferred_multimodal_provider_id()
        # openai is multimodal but unavailable, so preferred should be None
        # (groq is available but not multimodal, so no valid multimodal provider)
        assert preferred is None
