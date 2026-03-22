#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy — RemoteExecutionModeResolver
======================================

Canonical, reusable resolver that determines the appropriate
:class:`~core.schemas.remote_execution.RemoteExecutionMode` for a given
combination of device profile, task intent, and dispatch context.

This module is the **single authoritative place** in the Galaxy codebase
where the ``agent_runtime`` vs ``command_only`` decision is made.  All
dispatch paths — ``OpenClawd``, ``SwarmCoordinator``, ``smart_scheduler``
device selection — should delegate this decision here rather than embedding
ad-hoc branching logic.

Resolution rules (evaluated in priority order)
-----------------------------------------------
1. **Explicit override**: if *forced_mode* is supplied, it is returned
   directly with ``resolution_source = "forced"``.
2. **Task/intent requirement**: if the task context explicitly requires a
   specific mode (e.g. a raw command dispatch always needs ``command_only``),
   that requirement is honoured when the device profile supports it.
3. **Profile preferred mode**: use :attr:`DeviceExecutionProfile.preferred_mode`
   when the device profile is available and the mode is supported.
4. **Capability-based inference**: infer from
   :attr:`DeviceExecutionProfile.supports_agent_runtime`.
5. **Conservative fallback**: when profile data is absent or incomplete,
   default to ``command_only``.

Usage::

    from core.remote_execution_mode_resolver import (
        RemoteExecutionModeResolver,
        resolve_mode,
    )
    from core.device_execution_profile import build_rich_profile

    profile = build_rich_profile(device_id="phone_01")
    result = resolve_mode(profile=profile)
    print(result.mode)              # RemoteExecutionMode.agent_runtime
    print(result.resolution_source) # "profile_preferred"

    # Quick function-level call:
    mode = resolve_mode(profile=profile).mode
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("Galaxy.RemoteExecutionModeResolver")


# ---------------------------------------------------------------------------
# Result contract
# ---------------------------------------------------------------------------


class ModeResolutionResult(BaseModel):
    """The output of a single resolver invocation.

    Attributes
    ----------
    mode:
        The resolved :class:`~core.schemas.remote_execution.RemoteExecutionMode`
        value (as a stable string).
    resolution_source:
        A short label explaining which rule produced the result.  Possible
        values: ``"forced"``, ``"task_required"``, ``"profile_preferred"``,
        ``"capability_inferred"``, ``"fallback"``.
    profile_class:
        The :class:`~core.device_execution_profile.DeviceProfileClass` value
        used during resolution (``"rich"`` / ``"thin"`` / ``"unknown"``).
        ``None`` when no profile was available.
    device_id:
        The device identifier from the profile, if present.
    notes:
        Optional human-readable explanation of the resolution decision.
    failure_domain:
        PR-13: When the resolution required a fallback due to a capability
        mismatch or unsupported mode, this field carries the canonical
        :class:`~core.failure_domains.FailureDomain` value string that
        describes why the fallback was necessary.  ``None`` for non-fallback
        resolutions.
    """

    mode: str = Field(
        description="Resolved RemoteExecutionMode value string.",
    )
    resolution_source: str = Field(
        description="Rule that produced this resolution.",
    )
    profile_class: Optional[str] = Field(
        default=None,
        description="DeviceProfileClass used during resolution.",
    )
    device_id: Optional[str] = Field(
        default=None,
        description="Device identifier from the profile.",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Optional human-readable explanation.",
    )
    failure_domain: Optional[str] = Field(
        default=None,
        description=(
            "PR-13: Canonical failure domain when a fallback was required. "
            "None for non-fallback resolutions."
        ),
    )

    model_config = {"use_enum_values": True}

    def as_remote_execution_mode(self):
        """Return the resolved mode as a :class:`RemoteExecutionMode` enum.

        Importing the enum lazily so that this module has no hard dependency
        on ``core.schemas``, preserving testability in isolation.
        """
        from core.schemas.remote_execution import RemoteExecutionMode
        return RemoteExecutionMode(self.mode)


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class RemoteExecutionModeResolver:
    """Stateless resolver that maps device profile + task context to a mode.

    Parameters
    ----------
    default_mode:
        The conservative fallback mode used when all profile signals are
        absent or ambiguous.  Defaults to ``"command_only"``.
    """

    def __init__(self, default_mode: str = "command_only") -> None:
        self.default_mode = default_mode

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(
        self,
        *,
        profile: Optional[Any] = None,
        task_intent: Optional[str] = None,
        required_mode: Optional[str] = None,
        forced_mode: Optional[str] = None,
        dispatch_context: Optional[Dict[str, Any]] = None,
    ) -> ModeResolutionResult:
        """Determine the appropriate ``RemoteExecutionMode``.

        Parameters
        ----------
        profile:
            A :class:`~core.device_execution_profile.DeviceExecutionProfile`
            describing the target device.  When ``None``, the resolver falls
            back to the conservative default.
        task_intent:
            Optional task/intent type string (e.g. ``"agent_execute"``,
            ``"device_control"``, ``"screenshot"``).  Certain intents force
            ``command_only`` regardless of device capability.
        required_mode:
            Explicit mode requirement from the task context (bypasses
            capability inference but still validated against profile support).
        forced_mode:
            Absolute override — returned verbatim, skipping all other rules.
            Use only when the caller has already made a definitive decision.
        dispatch_context:
            Arbitrary extra context dict passed through for extension points.

        Returns
        -------
        ModeResolutionResult
        """
        # Rule 1: forced override
        if forced_mode is not None:
            _mode = self._normalise_mode(forced_mode)
            logger.debug(
                "RemoteExecutionModeResolver: forced mode=%s device_id=%s",
                _mode,
                getattr(profile, "device_id", None),
            )
            return ModeResolutionResult(
                mode=_mode,
                resolution_source="forced",
                profile_class=getattr(profile, "profile_class", None),
                device_id=getattr(profile, "device_id", None),
                notes=f"Forced by caller: {forced_mode}",
            )

        device_id = getattr(profile, "device_id", None)
        profile_class = getattr(profile, "profile_class", None)
        if profile_class is not None:
            profile_class = str(profile_class)

        # Rule 2: task/intent-level requirement
        if required_mode is not None:
            _mode = self._normalise_mode(required_mode)
            # Validate that the profile (if present) supports this mode
            if profile is not None and not profile.supports_mode(_mode):
                # Profile doesn't support the required mode → fallback
                # PR-13: classify as remote_capability_mismatch
                logger.warning(
                    "RemoteExecutionModeResolver: required_mode=%s not supported by "
                    "device=%s (profile_class=%s); falling back to %s",
                    _mode,
                    device_id,
                    profile_class,
                    self.default_mode,
                )
                return ModeResolutionResult(
                    mode=self.default_mode,
                    resolution_source="fallback",
                    profile_class=profile_class,
                    device_id=device_id,
                    failure_domain="remote_capability_mismatch",
                    notes=(
                        f"Required mode '{_mode}' not supported by device "
                        f"(profile_class={profile_class}); using fallback."
                    ),
                )
            logger.debug(
                "RemoteExecutionModeResolver: task_required mode=%s device_id=%s",
                _mode,
                device_id,
            )
            return ModeResolutionResult(
                mode=_mode,
                resolution_source="task_required",
                profile_class=profile_class,
                device_id=device_id,
                notes=f"Required by task context: {required_mode}",
            )

        # Command-dispatch intents always map to command_only
        if task_intent and self._is_command_only_intent(task_intent):
            logger.debug(
                "RemoteExecutionModeResolver: task_intent=%s → command_only device_id=%s",
                task_intent,
                device_id,
            )
            return ModeResolutionResult(
                mode="command_only",
                resolution_source="task_required",
                profile_class=profile_class,
                device_id=device_id,
                notes=f"Task intent '{task_intent}' requires command_only dispatch.",
            )

        # No profile — conservative fallback
        if profile is None:
            logger.debug(
                "RemoteExecutionModeResolver: no profile — using fallback mode=%s",
                self.default_mode,
            )
            return ModeResolutionResult(
                mode=self.default_mode,
                resolution_source="fallback",
                profile_class=None,
                device_id=None,
                failure_domain="remote_device_unavailable",
                notes="No device profile available; using conservative fallback.",
            )

        # Rule 3: profile preferred mode
        preferred = getattr(profile, "preferred_mode", None)
        if preferred is not None:
            _mode = self._normalise_mode(preferred)
            if profile.supports_mode(_mode):
                logger.debug(
                    "RemoteExecutionModeResolver: profile_preferred mode=%s device_id=%s",
                    _mode,
                    device_id,
                )
                return ModeResolutionResult(
                    mode=_mode,
                    resolution_source="profile_preferred",
                    profile_class=profile_class,
                    device_id=device_id,
                    notes=f"Using profile preferred mode (profile_class={profile_class}).",
                )

        # Rule 4: capability-based inference
        if profile.is_agent_runtime_capable():
            logger.debug(
                "RemoteExecutionModeResolver: capability_inferred agent_runtime device_id=%s",
                device_id,
            )
            return ModeResolutionResult(
                mode="agent_runtime",
                resolution_source="capability_inferred",
                profile_class=profile_class,
                device_id=device_id,
                notes="Device supports agent_runtime (inferred from capability flags).",
            )

        if profile.is_command_only_capable():
            logger.debug(
                "RemoteExecutionModeResolver: capability_inferred command_only device_id=%s",
                device_id,
            )
            return ModeResolutionResult(
                mode="command_only",
                resolution_source="capability_inferred",
                profile_class=profile_class,
                device_id=device_id,
                notes="Device supports command_only only (inferred from capability flags).",
            )

        # Rule 5: conservative fallback
        logger.warning(
            "RemoteExecutionModeResolver: insufficient profile data for device=%s — "
            "defaulting to %s",
            device_id,
            self.default_mode,
        )
        return ModeResolutionResult(
            mode=self.default_mode,
            resolution_source="fallback",
            profile_class=profile_class,
            device_id=device_id,
            failure_domain="remote_capability_mismatch",
            notes=(
                "Profile has no supported modes and no preferred mode; "
                "using conservative fallback."
            ),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_mode(mode: str) -> str:
        """Normalise a mode string to a canonical ``RemoteExecutionMode`` value."""
        if hasattr(mode, "value"):
            # Accept RemoteExecutionMode enum instances directly
            return mode.value
        lower = str(mode).lower()
        if lower in ("agent_runtime",):
            return "agent_runtime"
        if lower in ("command_only",):
            return "command_only"
        # Unknown value — leave as-is and let downstream validation catch it
        return str(mode)

    @staticmethod
    def _is_command_only_intent(task_intent: str) -> bool:
        """Return True when the task intent type requires command_only dispatch.

        Intents that produce structured commands (device_control, screenshot,
        take_screenshot, etc.) are always routed via command_only regardless
        of the device's richer capabilities.
        """
        _COMMAND_INTENTS = frozenset({
            "device_control",
            "take_screenshot",
            "screenshot",
            "click",
            "swipe",
            "keypress",
            "type_text",
            "send_command",
            "gateway_command",
        })
        return task_intent.lower() in _COMMAND_INTENTS


# ---------------------------------------------------------------------------
# Module-level singleton + convenience function
# ---------------------------------------------------------------------------

_default_resolver: Optional[RemoteExecutionModeResolver] = None


def get_resolver() -> RemoteExecutionModeResolver:
    """Return the process-level :class:`RemoteExecutionModeResolver` singleton."""
    global _default_resolver
    if _default_resolver is None:
        _default_resolver = RemoteExecutionModeResolver()
    return _default_resolver


def resolve_mode(
    *,
    profile: Optional[Any] = None,
    task_intent: Optional[str] = None,
    required_mode: Optional[str] = None,
    forced_mode: Optional[str] = None,
    dispatch_context: Optional[Dict[str, Any]] = None,
) -> ModeResolutionResult:
    """Module-level convenience wrapper around the singleton resolver.

    Parameters
    ----------
    profile:
        :class:`~core.device_execution_profile.DeviceExecutionProfile` for
        the target device.
    task_intent:
        Optional task/intent type string.
    required_mode:
        Explicit mode requirement from the task context.
    forced_mode:
        Absolute override.
    dispatch_context:
        Arbitrary extra context dict.

    Returns
    -------
    ModeResolutionResult
    """
    return get_resolver().resolve(
        profile=profile,
        task_intent=task_intent,
        required_mode=required_mode,
        forced_mode=forced_mode,
        dispatch_context=dispatch_context,
    )
