"""PR-10: multimodal runtime profile authority.

This module classifies the current multimodal runtime configuration into one of
three operator-facing deployment profiles:

* ``safe_default``   — conservative defaults, continuous ingest and WebRTC off
* ``full_deployment`` — active multimodal runtime features enabled
* ``debug_enhanced`` — debug/observability-heavy multimodal runtime posture

The goal is not to replace the existing config stack, but to make the current
runtime posture explicit and machine-checkable for diagnostics, status boards,
and reviewer-facing summaries.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from core.realtime_streaming_backbone import build_realtime_streaming_backbone_contract

MULTIMODAL_RUNTIME_PROFILE_IS_AUTHORITY = (
    "MULTIMODAL_RUNTIME_PROFILE::CONFIG_LAYERING_CLASSIFICATION_IS_AUTHORITY_PR10_V1"
)
MULTIMODAL_RUNTIME_PROFILE_PR10_SENTINEL = (
    "MULTIMODAL_RUNTIME_PROFILE::SAFE_DEFAULT_FULL_DEPLOYMENT_DEBUG_ENHANCED_V1"
)
_STREAMING_BACKBONE_CONTRACT: Optional[Dict[str, Any]] = None


def _get_streaming_backbone_contract() -> Dict[str, Any]:
    global _STREAMING_BACKBONE_CONTRACT
    if _STREAMING_BACKBONE_CONTRACT is None:
        _STREAMING_BACKBONE_CONTRACT = build_realtime_streaming_backbone_contract()
    return _STREAMING_BACKBONE_CONTRACT


class MultimodalRuntimeProfile(str, enum.Enum):
    """Named runtime profiles for the multimodal subsystem."""

    SAFE_DEFAULT = "safe_default"
    FULL_DEPLOYMENT = "full_deployment"
    DEBUG_ENHANCED = "debug_enhanced"


@dataclasses.dataclass(frozen=True)
class MultimodalRuntimeProfileSnapshot:
    """Serializable snapshot of the current multimodal runtime posture."""

    profile: MultimodalRuntimeProfile
    enable_multimodal_ingest: bool
    enable_webrtc_session_manager: bool
    debug_desktop_presence_runtime: bool
    state_event_bus_log_all: bool
    explicit_profile_override: Optional[str]
    rationale: str

    def to_dict(self) -> Dict[str, Any]:
        switch_policy = _get_streaming_backbone_contract().get("switch_and_degradation_policy", {})
        streaming_mainline_state = (
            "enabled" if self.enable_webrtc_session_manager else "discrete_fallback"
        )
        return {
            "authority": MULTIMODAL_RUNTIME_PROFILE_IS_AUTHORITY,
            "pr_sentinel": MULTIMODAL_RUNTIME_PROFILE_PR10_SENTINEL,
            "profile": self.profile.value,
            "enable_multimodal_ingest": self.enable_multimodal_ingest,
            "enable_webrtc_session_manager": self.enable_webrtc_session_manager,
            "debug_desktop_presence_runtime": self.debug_desktop_presence_runtime,
            "state_event_bus_log_all": self.state_event_bus_log_all,
            "explicit_profile_override": self.explicit_profile_override,
            "is_safe_default": self.profile == MultimodalRuntimeProfile.SAFE_DEFAULT,
            "is_full_deployment": self.profile == MultimodalRuntimeProfile.FULL_DEPLOYMENT,
            "is_debug_enhanced": self.profile == MultimodalRuntimeProfile.DEBUG_ENHANCED,
            "streaming_mainline_state": streaming_mainline_state,
            "streaming_switch_policy": switch_policy.get("switches", {}),
            "streaming_degradation_states": switch_policy.get("degradation_states", []),
            "streaming_discrete_fallback_rule": switch_policy.get(
                "discrete_fallback_rule", ""
            ),
            "rationale": self.rationale,
        }


_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSY = frozenset({"0", "false", "no", "off"})


def _parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in _TRUTHY:
        return True
    if normalized in _FALSY:
        return False
    return default


def _load_root_config_defaults() -> Dict[str, Any]:
    root = Path(__file__).resolve().parent.parent
    config_path = root / "config.json"
    if not config_path.exists():
        return {}
    try:
        with config_path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _resolve_flag(
    config: Mapping[str, Any],
    env: Mapping[str, str],
    *,
    config_key: str,
    env_key: str,
    default: bool = False,
) -> bool:
    if env_key in env:
        return _parse_bool(env.get(env_key), default)
    return _parse_bool(config.get(config_key), default)


def resolve_multimodal_runtime_profile(
    *,
    config: Optional[Mapping[str, Any]] = None,
    env: Optional[Mapping[str, str]] = None,
) -> MultimodalRuntimeProfileSnapshot:
    """Resolve the current multimodal runtime profile from config and env."""

    resolved_env: Mapping[str, str] = env if env is not None else os.environ
    resolved_config: Mapping[str, Any] = config if config is not None else _load_root_config_defaults()

    explicit_profile = str(
        resolved_env.get("GALAXY_MULTIMODAL_RUNTIME_PROFILE", "")
    ).strip().lower() or None

    enable_multimodal_ingest = _resolve_flag(
        resolved_config,
        resolved_env,
        config_key="enable_multimodal_ingest",
        env_key="GALAXY_ENABLE_MULTIMODAL_INGEST",
        default=False,
    )
    enable_webrtc_session_manager = _resolve_flag(
        resolved_config,
        resolved_env,
        config_key="enable_webrtc_session_manager",
        env_key="GALAXY_ENABLE_WEBRTC_SESSION_MANAGER",
        default=False,
    )
    debug_desktop_presence_runtime = _resolve_flag(
        resolved_config,
        resolved_env,
        config_key="debug_desktop_presence_runtime",
        env_key="GALAXY_DEBUG_DESKTOP_PRESENCE_RUNTIME",
        default=False,
    )
    state_event_bus_log_all = _resolve_flag(
        resolved_config,
        resolved_env,
        config_key="state_event_bus_log_all",
        env_key="GALAXY_STATE_EVENT_BUS_LOG_ALL",
        default=False,
    )

    if explicit_profile == MultimodalRuntimeProfile.DEBUG_ENHANCED.value:
        profile = MultimodalRuntimeProfile.DEBUG_ENHANCED
        rationale = "explicit GALAXY_MULTIMODAL_RUNTIME_PROFILE=debug_enhanced override"
    elif explicit_profile == MultimodalRuntimeProfile.FULL_DEPLOYMENT.value:
        profile = MultimodalRuntimeProfile.FULL_DEPLOYMENT
        rationale = "explicit GALAXY_MULTIMODAL_RUNTIME_PROFILE=full_deployment override"
    elif explicit_profile == MultimodalRuntimeProfile.SAFE_DEFAULT.value:
        profile = MultimodalRuntimeProfile.SAFE_DEFAULT
        rationale = "explicit GALAXY_MULTIMODAL_RUNTIME_PROFILE=safe_default override"
    elif debug_desktop_presence_runtime or state_event_bus_log_all:
        profile = MultimodalRuntimeProfile.DEBUG_ENHANCED
        rationale = (
            "debug_desktop_presence_runtime or state_event_bus_log_all is enabled, "
            "so the runtime is operating in an observability-heavy posture"
        )
    elif enable_multimodal_ingest or enable_webrtc_session_manager:
        profile = MultimodalRuntimeProfile.FULL_DEPLOYMENT
        rationale = (
            "continuous multimodal ingest or WebRTC session management is enabled, "
            "so the runtime is beyond the conservative safe-default posture"
        )
    else:
        profile = MultimodalRuntimeProfile.SAFE_DEFAULT
        rationale = (
            "continuous multimodal ingest and WebRTC session management are both disabled, "
            "matching the conservative safe-default runtime posture"
        )

    return MultimodalRuntimeProfileSnapshot(
        profile=profile,
        enable_multimodal_ingest=enable_multimodal_ingest,
        enable_webrtc_session_manager=enable_webrtc_session_manager,
        debug_desktop_presence_runtime=debug_desktop_presence_runtime,
        state_event_bus_log_all=state_event_bus_log_all,
        explicit_profile_override=explicit_profile,
        rationale=rationale,
    )


def build_multimodal_runtime_profile_summary(
    *,
    config: Optional[Mapping[str, Any]] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Return a JSON-safe summary of the resolved multimodal runtime profile."""

    return resolve_multimodal_runtime_profile(config=config, env=env).to_dict()
