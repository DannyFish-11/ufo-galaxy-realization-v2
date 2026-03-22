#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr6_device_execution_profiles.py
=============================================

Test suite for PR-6: device execution profiles and remote execution mode
resolution.

Covers:
- DeviceExecutionProfile schema correctness
- DeviceProfileClass classification
- Profile factory functions (build_rich/thin/unknown/from_device_info)
- RemoteExecutionModeResolver — all resolution rules
- Representative device classes (phone/tablet → agent_runtime, drone → command_only)
- Devices supporting both modes → deterministic selection
- Insufficient profile data → safe fallback
- Unsupported target → explicit fallback behaviour
- Integration: DeviceScoreInput carries execution_profile field
- Integration: resolve_mode + RemoteExecutionMode roundtrip
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# DeviceExecutionProfile
# ---------------------------------------------------------------------------


class TestDeviceExecutionProfileSchema:
    """Core schema fields and serialisation."""

    def test_default_profile_has_unknown_class(self):
        from core.device_execution_profile import DeviceExecutionProfile, DeviceProfileClass

        p = DeviceExecutionProfile(device_id="dev_x")
        assert p.profile_class == DeviceProfileClass.unknown

    def test_default_profile_does_not_support_agent_runtime(self):
        from core.device_execution_profile import DeviceExecutionProfile

        p = DeviceExecutionProfile(device_id="dev_x")
        assert p.supports_agent_runtime is False

    def test_default_profile_supports_command_only(self):
        from core.device_execution_profile import DeviceExecutionProfile

        p = DeviceExecutionProfile(device_id="dev_x")
        assert p.supports_command_only is True

    def test_derive_supported_modes_rich(self):
        from core.device_execution_profile import DeviceExecutionProfile, DeviceProfileClass

        p = DeviceExecutionProfile(
            device_id="dev_rich",
            profile_class=DeviceProfileClass.rich,
            supports_agent_runtime=True,
            supports_command_only=True,
        )
        modes = p.derive_supported_modes()
        assert "agent_runtime" in modes
        assert "command_only" in modes

    def test_derive_supported_modes_thin(self):
        from core.device_execution_profile import DeviceExecutionProfile, DeviceProfileClass

        p = DeviceExecutionProfile(
            device_id="dev_thin",
            profile_class=DeviceProfileClass.thin,
            supports_agent_runtime=False,
            supports_command_only=True,
        )
        modes = p.derive_supported_modes()
        assert "agent_runtime" not in modes
        assert "command_only" in modes

    def test_supports_mode_checks_derived_list(self):
        from core.device_execution_profile import DeviceExecutionProfile, DeviceProfileClass

        p = DeviceExecutionProfile(
            device_id="dev_rich",
            profile_class=DeviceProfileClass.rich,
            supports_agent_runtime=True,
            supports_command_only=True,
        )
        assert p.supports_mode("agent_runtime") is True
        assert p.supports_mode("command_only") is True

    def test_supports_mode_thin_device(self):
        from core.device_execution_profile import DeviceExecutionProfile, DeviceProfileClass

        p = DeviceExecutionProfile(
            device_id="dev_thin",
            profile_class=DeviceProfileClass.thin,
            supports_agent_runtime=False,
            supports_command_only=True,
        )
        assert p.supports_mode("command_only") is True
        assert p.supports_mode("agent_runtime") is False

    def test_to_dict_is_stable(self):
        from core.device_execution_profile import DeviceExecutionProfile, DeviceProfileClass

        p = DeviceExecutionProfile(
            device_id="dev_001",
            profile_class=DeviceProfileClass.rich,
            supports_agent_runtime=True,
            supports_command_only=True,
            capabilities=["screen", "touch"],
        )
        d = p.to_dict()
        assert isinstance(d, dict)
        assert d["device_id"] == "dev_001"
        assert "agent_runtime" in d["supported_modes"]

    def test_is_agent_runtime_capable(self):
        from core.device_execution_profile import DeviceExecutionProfile, DeviceProfileClass

        rich = DeviceExecutionProfile(
            device_id="r",
            profile_class=DeviceProfileClass.rich,
            supports_agent_runtime=True,
        )
        thin = DeviceExecutionProfile(
            device_id="t",
            profile_class=DeviceProfileClass.thin,
            supports_agent_runtime=False,
        )
        assert rich.is_agent_runtime_capable() is True
        assert thin.is_agent_runtime_capable() is False


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


class TestProfileFactories:
    """build_rich_profile / build_thin_profile / build_unknown_profile."""

    def test_build_rich_profile(self):
        from core.device_execution_profile import build_rich_profile, DeviceProfileClass

        p = build_rich_profile(device_id="phone_01", capabilities=["screen", "touch"])
        assert p.profile_class == DeviceProfileClass.rich
        assert p.supports_agent_runtime is True
        assert p.preferred_mode == "agent_runtime"
        assert "agent_runtime" in p.supported_modes
        assert "command_only" in p.supported_modes

    def test_build_thin_profile(self):
        from core.device_execution_profile import build_thin_profile, DeviceProfileClass

        p = build_thin_profile(device_id="drone_01", device_type="drone")
        assert p.profile_class == DeviceProfileClass.thin
        assert p.supports_agent_runtime is False
        assert p.preferred_mode == "command_only"
        assert "command_only" in p.supported_modes
        assert "agent_runtime" not in p.supported_modes

    def test_build_unknown_profile(self):
        from core.device_execution_profile import build_unknown_profile, DeviceProfileClass

        p = build_unknown_profile(device_id="mystery_01")
        assert p.profile_class == DeviceProfileClass.unknown
        assert p.preferred_mode == "command_only"
        assert "command_only" in p.supported_modes

    def test_build_profile_from_device_info_android(self):
        """Android device with screen/touch → rich profile."""
        from core.device_execution_profile import (
            build_profile_from_device_info,
            DeviceProfileClass,
        )

        info = {
            "device_id": "android_01",
            "device_type": "android",
            "capabilities": ["screen", "touch", "camera"],
        }
        p = build_profile_from_device_info(info)
        assert p.profile_class == DeviceProfileClass.rich
        assert p.supports_agent_runtime is True
        assert p.preferred_mode == "agent_runtime"

    def test_build_profile_from_device_info_drone(self):
        """Drone device → thin profile."""
        from core.device_execution_profile import (
            build_profile_from_device_info,
            DeviceProfileClass,
        )

        info = {
            "device_id": "drone_01",
            "device_type": "drone",
            "capabilities": ["gps", "accelerometer"],
        }
        p = build_profile_from_device_info(info)
        assert p.profile_class == DeviceProfileClass.thin
        assert p.supports_agent_runtime is False
        assert p.preferred_mode == "command_only"

    def test_build_profile_from_device_info_iot(self):
        """IoT sensor → thin profile."""
        from core.device_execution_profile import (
            build_profile_from_device_info,
            DeviceProfileClass,
        )

        info = {"device_type": "iot", "capabilities": ["temperature_sensor"]}
        p = build_profile_from_device_info(info)
        assert p.profile_class == DeviceProfileClass.thin

    def test_build_profile_from_device_info_empty(self):
        """No capability info → unknown profile with conservative fallback."""
        from core.device_execution_profile import (
            build_profile_from_device_info,
            DeviceProfileClass,
        )

        p = build_profile_from_device_info({})
        assert p.profile_class == DeviceProfileClass.unknown
        assert p.preferred_mode == "command_only"

    def test_build_profile_from_device_info_dict_caps(self):
        """Capabilities as list of dicts (Android bridge format) → normalised."""
        from core.device_execution_profile import (
            build_profile_from_device_info,
            DeviceProfileClass,
        )

        info = {
            "device_type": "android",
            "capabilities": [{"name": "screen"}, {"name": "touch"}],
        }
        p = build_profile_from_device_info(info)
        assert p.profile_class == DeviceProfileClass.rich
        assert "screen" in p.capabilities
        assert "touch" in p.capabilities

    def test_build_profile_from_device_info_pre_built_dict(self):
        """Pre-built profile dict in device_info is used directly."""
        from core.device_execution_profile import (
            build_profile_from_device_info,
            DeviceProfileClass,
        )

        pre = {
            "device_id": "dev_x",
            "profile_class": "rich",
            "supports_agent_runtime": True,
            "supports_command_only": True,
            "preferred_mode": "agent_runtime",
            "supported_modes": ["agent_runtime", "command_only"],
        }
        info = {"execution_profile": pre}
        p = build_profile_from_device_info(info)
        assert p.profile_class == DeviceProfileClass.rich
        assert p.supports_agent_runtime is True

    def test_build_profile_from_device_info_passthrough_profile_object(self):
        """Pre-built DeviceExecutionProfile object in device_info is returned directly."""
        from core.device_execution_profile import (
            build_profile_from_device_info,
            build_rich_profile,
        )

        pre = build_rich_profile(device_id="phone_pre")
        info = {"execution_profile": pre}
        p = build_profile_from_device_info(info)
        assert p is pre


# ---------------------------------------------------------------------------
# RemoteExecutionModeResolver
# ---------------------------------------------------------------------------


class TestModeResolutionResult:
    """ModeResolutionResult contract."""

    def test_as_remote_execution_mode_agent_runtime(self):
        from core.remote_execution_mode_resolver import ModeResolutionResult
        from core.schemas.remote_execution import RemoteExecutionMode

        r = ModeResolutionResult(mode="agent_runtime", resolution_source="forced")
        assert r.as_remote_execution_mode() == RemoteExecutionMode.agent_runtime

    def test_as_remote_execution_mode_command_only(self):
        from core.remote_execution_mode_resolver import ModeResolutionResult
        from core.schemas.remote_execution import RemoteExecutionMode

        r = ModeResolutionResult(mode="command_only", resolution_source="fallback")
        assert r.as_remote_execution_mode() == RemoteExecutionMode.command_only


class TestRemoteExecutionModeResolverForcedOverride:
    """Rule 1: forced_mode always wins."""

    def test_forced_agent_runtime(self):
        from core.remote_execution_mode_resolver import RemoteExecutionModeResolver

        resolver = RemoteExecutionModeResolver()
        result = resolver.resolve(forced_mode="agent_runtime")
        assert result.mode == "agent_runtime"
        assert result.resolution_source == "forced"

    def test_forced_command_only(self):
        from core.remote_execution_mode_resolver import RemoteExecutionModeResolver

        resolver = RemoteExecutionModeResolver()
        result = resolver.resolve(forced_mode="command_only")
        assert result.mode == "command_only"
        assert result.resolution_source == "forced"

    def test_forced_overrides_profile(self):
        from core.device_execution_profile import build_rich_profile
        from core.remote_execution_mode_resolver import RemoteExecutionModeResolver

        profile = build_rich_profile(device_id="p1")
        resolver = RemoteExecutionModeResolver()
        result = resolver.resolve(profile=profile, forced_mode="command_only")
        assert result.mode == "command_only"
        assert result.resolution_source == "forced"


class TestRemoteExecutionModeResolverTaskRequired:
    """Rule 2: required_mode / command-dispatch intents."""

    def test_required_mode_respected_when_supported(self):
        from core.device_execution_profile import build_rich_profile
        from core.remote_execution_mode_resolver import RemoteExecutionModeResolver

        profile = build_rich_profile(device_id="p1")
        resolver = RemoteExecutionModeResolver()
        result = resolver.resolve(profile=profile, required_mode="command_only")
        assert result.mode == "command_only"
        assert result.resolution_source == "task_required"

    def test_required_mode_falls_back_when_not_supported(self):
        """thin device cannot support agent_runtime → fallback."""
        from core.device_execution_profile import build_thin_profile
        from core.remote_execution_mode_resolver import RemoteExecutionModeResolver

        profile = build_thin_profile(device_id="drone")
        resolver = RemoteExecutionModeResolver()
        result = resolver.resolve(profile=profile, required_mode="agent_runtime")
        assert result.mode == "command_only"
        assert result.resolution_source == "fallback"

    def test_command_intent_maps_to_command_only(self):
        from core.device_execution_profile import build_rich_profile
        from core.remote_execution_mode_resolver import RemoteExecutionModeResolver

        profile = build_rich_profile(device_id="phone_01")
        resolver = RemoteExecutionModeResolver()
        result = resolver.resolve(profile=profile, task_intent="take_screenshot")
        assert result.mode == "command_only"
        assert result.resolution_source == "task_required"

    def test_device_control_intent_maps_to_command_only(self):
        from core.device_execution_profile import build_rich_profile
        from core.remote_execution_mode_resolver import RemoteExecutionModeResolver

        profile = build_rich_profile(device_id="phone_01")
        resolver = RemoteExecutionModeResolver()
        result = resolver.resolve(profile=profile, task_intent="device_control")
        assert result.mode == "command_only"
        assert result.resolution_source == "task_required"


class TestRemoteExecutionModeResolverProfilePreferred:
    """Rule 3: profile preferred mode."""

    def test_rich_profile_prefers_agent_runtime(self):
        from core.device_execution_profile import build_rich_profile
        from core.remote_execution_mode_resolver import RemoteExecutionModeResolver

        profile = build_rich_profile(device_id="phone_01")
        resolver = RemoteExecutionModeResolver()
        result = resolver.resolve(profile=profile)
        assert result.mode == "agent_runtime"
        assert result.resolution_source == "profile_preferred"
        assert result.profile_class == "rich"
        assert result.device_id == "phone_01"

    def test_thin_profile_prefers_command_only(self):
        from core.device_execution_profile import build_thin_profile
        from core.remote_execution_mode_resolver import RemoteExecutionModeResolver

        profile = build_thin_profile(device_id="drone_01")
        resolver = RemoteExecutionModeResolver()
        result = resolver.resolve(profile=profile)
        assert result.mode == "command_only"
        assert result.resolution_source in ("profile_preferred", "capability_inferred")


class TestRemoteExecutionModeResolverFallback:
    """Rule 5: conservative fallback for missing/insufficient data."""

    def test_no_profile_fallback_to_command_only(self):
        from core.remote_execution_mode_resolver import RemoteExecutionModeResolver

        resolver = RemoteExecutionModeResolver()
        result = resolver.resolve(profile=None)
        assert result.mode == "command_only"
        assert result.resolution_source == "fallback"
        assert result.profile_class is None

    def test_unknown_profile_fallback(self):
        from core.device_execution_profile import build_unknown_profile
        from core.remote_execution_mode_resolver import RemoteExecutionModeResolver

        profile = build_unknown_profile(device_id="mystery")
        resolver = RemoteExecutionModeResolver()
        result = resolver.resolve(profile=profile)
        assert result.mode == "command_only"

    def test_custom_default_mode_respected(self):
        from core.remote_execution_mode_resolver import RemoteExecutionModeResolver

        resolver = RemoteExecutionModeResolver(default_mode="command_only")
        result = resolver.resolve(profile=None)
        assert result.mode == "command_only"


# ---------------------------------------------------------------------------
# Representative device class scenarios
# ---------------------------------------------------------------------------


class TestRepresentativeDeviceScenarios:
    """End-to-end profile + resolver scenarios for real device classes."""

    def test_phone_resolves_to_agent_runtime(self):
        """Phone/tablet → rich profile → agent_runtime."""
        from core.device_execution_profile import build_profile_from_device_info
        from core.remote_execution_mode_resolver import resolve_mode

        info = {"device_type": "android", "capabilities": ["screen", "touch", "camera"]}
        profile = build_profile_from_device_info(info, device_id="phone_01")
        result = resolve_mode(profile=profile)
        assert result.mode == "agent_runtime"

    def test_tablet_resolves_to_agent_runtime(self):
        from core.device_execution_profile import build_profile_from_device_info
        from core.remote_execution_mode_resolver import resolve_mode

        info = {"device_type": "tablet", "capabilities": ["screen", "touch"]}
        profile = build_profile_from_device_info(info, device_id="tablet_01")
        result = resolve_mode(profile=profile)
        assert result.mode == "agent_runtime"

    def test_drone_resolves_to_command_only(self):
        """Drone → thin profile → command_only."""
        from core.device_execution_profile import build_profile_from_device_info
        from core.remote_execution_mode_resolver import resolve_mode

        info = {"device_type": "drone", "capabilities": ["gps", "camera"]}
        profile = build_profile_from_device_info(info, device_id="drone_01")
        result = resolve_mode(profile=profile)
        assert result.mode == "command_only"

    def test_iot_sensor_resolves_to_command_only(self):
        from core.device_execution_profile import build_profile_from_device_info
        from core.remote_execution_mode_resolver import resolve_mode

        info = {"device_type": "iot", "capabilities": ["temperature_sensor"]}
        profile = build_profile_from_device_info(info, device_id="sensor_01")
        result = resolve_mode(profile=profile)
        assert result.mode == "command_only"

    def test_windows_pc_resolves_to_agent_runtime(self):
        from core.device_execution_profile import build_profile_from_device_info
        from core.remote_execution_mode_resolver import resolve_mode

        info = {"device_type": "windows", "capabilities": ["screen", "keyboard"]}
        profile = build_profile_from_device_info(info, device_id="pc_01")
        result = resolve_mode(profile=profile)
        assert result.mode == "agent_runtime"

    def test_device_supporting_both_modes_deterministic(self):
        """Device that supports both modes should deterministically resolve to agent_runtime
        (profile preferred) when no task constraint overrides the choice."""
        from core.device_execution_profile import build_rich_profile
        from core.remote_execution_mode_resolver import resolve_mode

        profile = build_rich_profile(device_id="dual_device_01")
        assert profile.supports_mode("agent_runtime") is True
        assert profile.supports_mode("command_only") is True

        # Without any constraint, agent_runtime is preferred
        result = resolve_mode(profile=profile)
        assert result.mode == "agent_runtime"

        # With a command intent, command_only overrides
        result2 = resolve_mode(profile=profile, task_intent="take_screenshot")
        assert result2.mode == "command_only"

    def test_insufficient_profile_data_safe_fallback(self):
        """When no profile information is provided, fallback to command_only."""
        from core.remote_execution_mode_resolver import resolve_mode

        result = resolve_mode(profile=None)
        assert result.mode == "command_only"
        assert result.resolution_source == "fallback"

    def test_unsupported_target_unknown_profile_fallback(self):
        """Unknown profile always resolves conservatively to command_only."""
        from core.device_execution_profile import build_unknown_profile
        from core.remote_execution_mode_resolver import resolve_mode

        profile = build_unknown_profile(device_id="unknown_device_01")
        result = resolve_mode(profile=profile)
        assert result.mode == "command_only"


# ---------------------------------------------------------------------------
# DeviceScoreInput execution_profile field (smart_scheduler integration)
# ---------------------------------------------------------------------------


class TestDeviceScoreInputExecutionProfile:
    """DeviceScoreInput carries an optional execution_profile field (PR-6)."""

    def test_device_score_input_accepts_execution_profile(self):
        from core.control_plane.smart_scheduler import DeviceScoreInput
        from core.device_execution_profile import build_rich_profile

        profile = build_rich_profile(device_id="dev_001")
        dsi = DeviceScoreInput(
            device_id="dev_001",
            capabilities=["screen", "touch"],
            execution_profile=profile,
        )
        assert dsi.execution_profile is profile

    def test_device_score_input_default_execution_profile_is_none(self):
        from core.control_plane.smart_scheduler import DeviceScoreInput

        dsi = DeviceScoreInput(device_id="dev_002")
        assert dsi.execution_profile is None

    def test_device_score_input_scoring_unaffected_by_profile(self):
        """The scoring formula does not change when execution_profile is present."""
        from core.control_plane.smart_scheduler import DeviceScoreInput, DeviceScoringEngine
        from core.device_execution_profile import build_rich_profile

        engine = DeviceScoringEngine()
        without = DeviceScoreInput(device_id="d1", capabilities=["screen"])
        with_profile = DeviceScoreInput(
            device_id="d1",
            capabilities=["screen"],
            execution_profile=build_rich_profile(device_id="d1"),
        )
        score_without = engine.score_device(without, required_capabilities=["screen"])
        score_with = engine.score_device(with_profile, required_capabilities=["screen"])
        assert abs(score_without.total - score_with.total) < 1e-9

    def test_device_score_input_serialisation_excludes_execution_profile(self):
        """execution_profile is excluded from model_dump to keep the wire format stable."""
        from core.control_plane.smart_scheduler import DeviceScoreInput
        from core.device_execution_profile import build_rich_profile

        dsi = DeviceScoreInput(
            device_id="dev_003",
            execution_profile=build_rich_profile(device_id="dev_003"),
        )
        dumped = dsi.model_dump()
        assert "execution_profile" not in dumped


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------


class TestResolveModuleFunction:
    """resolve_mode convenience function."""

    def test_resolve_mode_function_rich_profile(self):
        from core.device_execution_profile import build_rich_profile
        from core.remote_execution_mode_resolver import resolve_mode

        profile = build_rich_profile(device_id="ph")
        result = resolve_mode(profile=profile)
        assert result.mode == "agent_runtime"

    def test_resolve_mode_function_no_profile(self):
        from core.remote_execution_mode_resolver import resolve_mode

        result = resolve_mode()
        assert result.mode == "command_only"
        assert result.resolution_source == "fallback"

    def test_resolve_mode_returns_correct_enum(self):
        from core.device_execution_profile import build_rich_profile
        from core.remote_execution_mode_resolver import resolve_mode
        from core.schemas.remote_execution import RemoteExecutionMode

        profile = build_rich_profile(device_id="ph")
        result = resolve_mode(profile=profile)
        assert result.as_remote_execution_mode() == RemoteExecutionMode.agent_runtime

    def test_resolve_mode_forced_returns_correct_enum(self):
        from core.remote_execution_mode_resolver import resolve_mode
        from core.schemas.remote_execution import RemoteExecutionMode

        result = resolve_mode(forced_mode="command_only")
        assert result.as_remote_execution_mode() == RemoteExecutionMode.command_only

    def test_get_resolver_singleton(self):
        from core.remote_execution_mode_resolver import get_resolver, RemoteExecutionModeResolver

        r1 = get_resolver()
        r2 = get_resolver()
        assert r1 is r2
        assert isinstance(r1, RemoteExecutionModeResolver)
