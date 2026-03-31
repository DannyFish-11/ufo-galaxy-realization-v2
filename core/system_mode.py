"""
Galaxy — System Mode Configuration Baseline
============================================

**AUTHORITY NOTICE**
--------------------
This module is the **canonical source of truth** for Galaxy startup and
fabric mode resolution.  All other modules that previously inferred
``desktop-local`` vs ``desktop-cross-device`` behaviour from scattered
environment variables (``GALAXY_NATS_URL``, ``GALAXY_CROSS_DEVICE_ENABLED``,
etc.) should consume :func:`resolve_fabric_config` instead.

System Modes
------------
``desktop-local`` (default)
    Clone-first / single-machine startup.  Cross-device fabric is not
    assumed.  NATS is not implicitly required.  Startup proceeds even when
    NATS is unavailable.

``desktop-cross-device``
    Explicit opt-in mode for the cross-device fabric.  NATS and
    control-plane dependencies may be treated as required by startup logic.
    Components can branch on :attr:`FabricConfig.nats_required` to enforce
    strict startup behaviour.

Environment Variables (canonical config contract)
-------------------------------------------------
``GALAXY_SYSTEM_MODE``
    ``desktop-local`` | ``desktop-cross-device``.
    Default: ``desktop-local``.

``GALAXY_NATS_ENABLED``
    ``false`` | ``true``.  When ``true`` the NATS bus is activated and
    mode-derived logic may treat it as required.
    Default: derived from ``GALAXY_SYSTEM_MODE``
    (``false`` for ``desktop-local``, ``true`` for ``desktop-cross-device``).

``GALAXY_NATS_URL``
    NATS server URL.  Presence implicitly activates NATS even in
    ``desktop-local`` mode (preserved backward compat).
    Default: ``nats://localhost:4222``.

``GALAXY_FABRIC_STRICT``
    ``false`` | ``true``.  When ``true`` the system treats missing
    fabric dependencies (e.g. NATS offline) as a hard startup failure
    instead of degrading gracefully.
    Default: ``false``.

``GALAXY_NETWORK_MODE``
    ``local`` | ``lan`` | ``tailscale`` | ``relay``.
    Describes the intended network topology.
    Default: ``local``.

``GALAXY_CROSS_DEVICE_ENABLED``
    ``false`` | ``true`` (or ``0``/``1``).  Alias understood by the legacy
    gateway switch.  When the explicit ``GALAXY_SYSTEM_MODE`` is absent this
    variable participates in mode derivation: ``true``/``1`` implies
    ``desktop-cross-device``.
    Default: derived from ``GALAXY_SYSTEM_MODE``.

``GALAXY_TAILSCALE_ENABLED``
    ``false`` | ``true``.  Marks that the host has Tailscale available.
    Default: ``false``.

``GALAXY_TAILSCALE_HOST``
    Tailscale hostname/IP for this node.

``GALAXY_TRANSPORT_PRIORITY``
    Comma-separated ordered list of transports the system should prefer,
    e.g. ``tailscale,lan,internet``.
    Default: ``lan,internet`` for ``desktop-local``;
             ``tailscale,lan,internet`` for ``desktop-cross-device``.

Usage
-----
::

    from core.system_mode import resolve_fabric_config, SystemMode

    cfg = resolve_fabric_config()
    if cfg.mode == SystemMode.DESKTOP_CROSS_DEVICE:
        # activate fabric, treat NATS as required if cfg.fabric_strict
        ...

The module-level singleton :data:`FABRIC_CONFIG` is resolved once at import
time and is safe to use throughout the application lifetime.  Use
:func:`resolve_fabric_config` directly in tests to pass custom env overrides.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

logger = logging.getLogger("Galaxy.SystemMode")

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

#: Module-level sentinel.  Other modules may import this to declare that
#: their mode-branching logic is derived from this module.
SYSTEM_MODE_CONFIG_AUTHORITY: str = "core.system_mode"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SystemMode(str, Enum):
    """Canonical Galaxy system operating modes."""

    DESKTOP_LOCAL = "desktop-local"
    """Default mode after clone.  No cross-device fabric assumed."""

    DESKTOP_CROSS_DEVICE = "desktop-cross-device"
    """Explicit cross-device fabric mode.  NATS / control-plane active."""


class NetworkMode(str, Enum):
    """Network topology modes."""

    LOCAL = "local"
    LAN = "lan"
    TAILSCALE = "tailscale"
    RELAY = "relay"


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FabricConfig:
    """Resolved fabric/startup configuration.

    All fields are derived from environment variables by
    :func:`resolve_fabric_config`.  The object is immutable so it can be
    safely shared across threads.

    Attributes
    ----------
    mode:
        The resolved :class:`SystemMode`.
    nats_enabled:
        Whether the NATS bus should be activated.
    nats_url:
        NATS server URL (always populated with a default even when NATS is
        disabled, so components do not need to guard against ``None``).
    nats_required:
        ``True`` when NATS failures should be treated as hard errors.
        This is ``True`` only when both ``nats_enabled`` and
        ``fabric_strict`` are ``True``.
    fabric_strict:
        Whether missing fabric dependencies cause hard startup failure.
    network_mode:
        The intended network topology.
    cross_device_enabled:
        Whether cross-device routing is active.
    tailscale_enabled:
        Whether Tailscale networking is available on this host.
    tailscale_host:
        Tailscale hostname for this node (may be empty string).
    transport_priority:
        Ordered list of preferred transports.
    """

    mode: SystemMode
    nats_enabled: bool
    nats_url: str
    nats_required: bool
    fabric_strict: bool
    network_mode: NetworkMode
    cross_device_enabled: bool
    tailscale_enabled: bool
    tailscale_host: str
    transport_priority: List[str]

    # -- Convenience helpers ------------------------------------------------

    @property
    def is_desktop_local(self) -> bool:
        """Return ``True`` when running in ``desktop-local`` mode."""
        return self.mode == SystemMode.DESKTOP_LOCAL

    @property
    def is_cross_device(self) -> bool:
        """Return ``True`` when running in ``desktop-cross-device`` mode."""
        return self.mode == SystemMode.DESKTOP_CROSS_DEVICE

    def as_dict(self) -> dict:
        """Return a JSON-serialisable representation of the config."""
        return {
            "mode": self.mode.value,
            "nats_enabled": self.nats_enabled,
            "nats_url": self.nats_url,
            "nats_required": self.nats_required,
            "fabric_strict": self.fabric_strict,
            "network_mode": self.network_mode.value,
            "cross_device_enabled": self.cross_device_enabled,
            "tailscale_enabled": self.tailscale_enabled,
            "tailscale_host": self.tailscale_host,
            "transport_priority": list(self.transport_priority),
        }


# ---------------------------------------------------------------------------
# Internal helpers (read env at call-time so tests can monkeypatch)
# ---------------------------------------------------------------------------

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSY = frozenset({"0", "false", "no", "off"})

_DEFAULT_NATS_URL = "nats://localhost:4222"
_TRANSPORT_LOCAL = ["lan", "internet"]
_TRANSPORT_CROSS_DEVICE = ["tailscale", "lan", "internet"]


def _parse_bool(value: str, default: bool) -> bool:
    """Parse a string env-var value as a boolean.

    Recognised truthy values (case-insensitive): ``1``, ``true``, ``yes``, ``on``.
    Recognised falsy values (case-insensitive): ``0``, ``false``, ``no``, ``off``.
    Any other value returns *default*.
    """
    v = value.strip().lower()
    if v in _TRUTHY:
        return True
    if v in _FALSY:
        return False
    return default


def _resolve_mode(env: Optional[str], cross_device_env: Optional[str]) -> SystemMode:
    """Derive the canonical :class:`SystemMode` from raw env strings.

    ``GALAXY_SYSTEM_MODE`` takes priority.  When absent,
    ``GALAXY_CROSS_DEVICE_ENABLED=1/true/yes`` implies
    ``desktop-cross-device``; all other values default to
    ``desktop-local``.
    """
    if env:
        normalized = env.strip().lower()
        if normalized == SystemMode.DESKTOP_CROSS_DEVICE.value:
            return SystemMode.DESKTOP_CROSS_DEVICE
        if normalized == SystemMode.DESKTOP_LOCAL.value:
            return SystemMode.DESKTOP_LOCAL
        logger.warning(
            "Unknown GALAXY_SYSTEM_MODE=%r; falling back to 'desktop-local'", env
        )

    # Fallback: infer from legacy GALAXY_CROSS_DEVICE_ENABLED
    if cross_device_env is not None:
        if cross_device_env.strip().lower() in _TRUTHY:
            return SystemMode.DESKTOP_CROSS_DEVICE
        if cross_device_env.strip().lower() in _FALSY:
            return SystemMode.DESKTOP_LOCAL

    return SystemMode.DESKTOP_LOCAL


def _resolve_network_mode(env: Optional[str]) -> NetworkMode:
    """Parse ``GALAXY_NETWORK_MODE`` into a :class:`NetworkMode`."""
    if env:
        normalized = env.strip().lower()
        try:
            return NetworkMode(normalized)
        except ValueError:
            logger.warning(
                "Unknown GALAXY_NETWORK_MODE=%r; falling back to 'local'", env
            )
    return NetworkMode.LOCAL


def _resolve_transport_priority(env: Optional[str], mode: SystemMode) -> List[str]:
    """Return the ordered transport priority list.

    Precedence:
    1. Explicit ``GALAXY_TRANSPORT_PRIORITY`` env var (comma-separated) — always wins.
    2. Mode-derived default:
       - ``desktop-cross-device`` → ``["tailscale", "lan", "internet"]``
       - ``desktop-local`` → ``["lan", "internet"]``
    """
    if env:
        items = [t.strip() for t in env.split(",") if t.strip()]
        if items:
            return items
    return list(
        _TRANSPORT_CROSS_DEVICE
        if mode == SystemMode.DESKTOP_CROSS_DEVICE
        else _TRANSPORT_LOCAL
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_fabric_config(environ: Optional[dict] = None) -> FabricConfig:
    """Build a :class:`FabricConfig` from environment variables.

    Parameters
    ----------
    environ:
        Optional dict of environment variables.  Defaults to
        ``os.environ``.  Pass a custom dict in tests to avoid
        monkeypatching global state.

    Returns
    -------
    FabricConfig
        Resolved, immutable configuration object.
    """
    env = environ if environ is not None else os.environ

    raw_mode = env.get("GALAXY_SYSTEM_MODE", "")
    raw_cross_device = env.get("GALAXY_CROSS_DEVICE_ENABLED")
    mode = _resolve_mode(raw_mode or None, raw_cross_device)

    # NATS
    nats_url = env.get("GALAXY_NATS_URL", "").strip() or _DEFAULT_NATS_URL
    nats_url_explicitly_set = bool(env.get("GALAXY_NATS_URL", "").strip())

    raw_nats_enabled = env.get("GALAXY_NATS_ENABLED", "")
    if raw_nats_enabled.strip():
        nats_enabled = _parse_bool(raw_nats_enabled, default=False)
    else:
        # Derive: explicitly set URL or cross-device mode → enabled
        nats_enabled = nats_url_explicitly_set or (mode == SystemMode.DESKTOP_CROSS_DEVICE)

    # Fabric strict
    raw_strict = env.get("GALAXY_FABRIC_STRICT", "")
    fabric_strict = _parse_bool(raw_strict, default=False)

    # NATS is only *required* (i.e. hard-fail on absence) when strict mode
    # is on AND NATS is explicitly enabled.
    nats_required = nats_enabled and fabric_strict

    # Network mode
    network_mode = _resolve_network_mode(env.get("GALAXY_NETWORK_MODE"))

    # Cross-device (normalise back from derived mode if not explicitly set)
    if raw_cross_device is not None:
        cross_device_enabled = _parse_bool(raw_cross_device, default=False)
    else:
        cross_device_enabled = mode == SystemMode.DESKTOP_CROSS_DEVICE

    # Tailscale
    raw_tailscale = env.get("GALAXY_TAILSCALE_ENABLED", "")
    tailscale_enabled = _parse_bool(raw_tailscale, default=False)
    tailscale_host = env.get("GALAXY_TAILSCALE_HOST", "").strip()

    # Transport priority
    raw_transport = env.get("GALAXY_TRANSPORT_PRIORITY", "")
    transport_priority = _resolve_transport_priority(raw_transport, mode)

    cfg = FabricConfig(
        mode=mode,
        nats_enabled=nats_enabled,
        nats_url=nats_url,
        nats_required=nats_required,
        fabric_strict=fabric_strict,
        network_mode=network_mode,
        cross_device_enabled=cross_device_enabled,
        tailscale_enabled=tailscale_enabled,
        tailscale_host=tailscale_host,
        transport_priority=transport_priority,
    )

    logger.debug(
        "SystemMode resolved: mode=%s nats_enabled=%s nats_required=%s "
        "fabric_strict=%s network_mode=%s cross_device=%s",
        cfg.mode.value,
        cfg.nats_enabled,
        cfg.nats_required,
        cfg.fabric_strict,
        cfg.network_mode.value,
        cfg.cross_device_enabled,
    )

    return cfg


# ---------------------------------------------------------------------------
# Module-level singleton (resolved at import time from os.environ)
# ---------------------------------------------------------------------------

#: Singleton resolved at import time.  Re-import the module or call
#: :func:`resolve_fabric_config` directly to obtain a fresh object in tests.
FABRIC_CONFIG: FabricConfig = resolve_fabric_config()


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    "SYSTEM_MODE_CONFIG_AUTHORITY",
    "SystemMode",
    "NetworkMode",
    "FabricConfig",
    "resolve_fabric_config",
    "FABRIC_CONFIG",
]
