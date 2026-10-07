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
    ``false`` | ``true`` (or ``0``/``1``).  The panel's "跨设备" button writes
    this key (and ``GALAXY_SYSTEM_MODE`` with it, so the two never disagree).
    Default: derived from ``GALAXY_SYSTEM_MODE``.

**One rule decides the mode** (:func:`cross_device_requested`): the system is in
``desktop-cross-device`` when *either* ``GALAXY_SYSTEM_MODE`` says
``desktop-cross-device`` *or* ``GALAXY_CROSS_DEVICE_ENABLED`` is true.  "Local" is the
factory default, so seeing it in a file (``.env.example`` ships it, "save settings"
writes it) is not a choice and never overrides an explicit opt-in anywhere else.
The startup orchestrator, the gateway switch, the desktop presence runtime and the
startup health check all call that one function instead of deriving the answer again.
``GALAXY_NATS_URL`` does **not** take part: it says *where* the bus is, not *which
mode* the system runs in.

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
from dataclasses import dataclass
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

    Cross-device when *either* ``GALAXY_SYSTEM_MODE=desktop-cross-device`` *or*
    ``GALAXY_CROSS_DEVICE_ENABLED=1/true/yes/on``; otherwise local.  An explicit
    ``desktop-local`` is the factory default and does not override the other key.
    """
    if env:
        normalized = env.strip().lower()
        if normalized == SystemMode.DESKTOP_CROSS_DEVICE.value:
            return SystemMode.DESKTOP_CROSS_DEVICE
        if normalized != SystemMode.DESKTOP_LOCAL.value:
            logger.warning("Unknown GALAXY_SYSTEM_MODE=%r; falling back to 'desktop-local'", env)

    if cross_device_env is not None and cross_device_env.strip().lower() in _TRUTHY:
        return SystemMode.DESKTOP_CROSS_DEVICE

    return SystemMode.DESKTOP_LOCAL


def cross_device_requested(environ: Optional[dict] = None) -> bool:
    """Is this system in cross-device mode?  **The** answer — nobody derives it again.

    Reads the environment at call time (the gateway switch is toggled live and
    tests monkeypatch it), using the same rule as :func:`resolve_fabric_config`.
    """
    env = environ if environ is not None else os.environ
    mode = _resolve_mode(env.get("GALAXY_SYSTEM_MODE") or None, env.get("GALAXY_CROSS_DEVICE_ENABLED"))
    return mode == SystemMode.DESKTOP_CROSS_DEVICE


def master_brain_wanted(environ: Optional[dict] = None) -> bool:
    """``GALAXY_MASTER_BRAIN_ENABLED`` 写成了开 —— 不管当前是什么模式。"""
    env = environ if environ is not None else os.environ
    return str(env.get("GALAXY_MASTER_BRAIN_ENABLED", "")).strip().lower() in _TRUTHY


def master_brain_requested(environ: Optional[dict] = None) -> bool:
    """主脑 / worker 该不该起：主脑开关开着，**并且**在跨设备模式里。

    跨设备是多设备的前提：本地模式下没有别的设备可调度，主脑与 worker 不起。
    开关开着却在本地模式 —— 那是一个没生效的配置，不是悄悄忽略：``master_brain_waiting_for_mode``
    让启动序列把它说出来。
    """
    return master_brain_wanted(environ) and cross_device_requested(environ)


def master_brain_waiting_for_mode(environ: Optional[dict] = None) -> bool:
    """主脑开关开着、但当前是本地模式，所以没起。"""
    return master_brain_wanted(environ) and not cross_device_requested(environ)


def master_brain_idle_status(log: logging.Logger) -> str:
    """主脑没起时启动序列要记的状态；开关开着却在本地模式 → 说出来（不悄悄忽略一个写了的配置）。"""
    if master_brain_waiting_for_mode():
        log.warning("主脑开关已开,但当前是本地模式(只用本机)—— 主脑与 worker 不起;要用请先打开「跨设备」")
        return "waiting_for_cross_device_mode"
    return "disabled"


def cross_device_refusal(trace_id: Optional[str] = None) -> Optional[dict]:
    """本地模式下，往别的设备下发命令的统一拒绝；跨设备模式下返回 ``None``（放行）。

    本地模式只用这台电脑。每一个「把命令送到另一台设备」的入口（并行 / 单设备命令 REST、命令路由的设备执行桥、
    智能体的 ``devices__invoke``、网关的单设备下发）都调它，说法一致：``error == "cross_device_disabled"``
    （与网关 ``galaxy_gateway.cross_device_switch`` 同一个错误码），并告诉人 / 模型怎么办。
    """
    if cross_device_requested():
        return None
    out = {
        "success": False,
        "error": "cross_device_disabled",
        "message": "当前是本地模式(只用本机),没有向别的设备下发。要用别的设备,请先打开「跨设备」。",
        "how_to_fix": "面板「跨设备」按钮打开(要重启才完全生效);智能体可调 devices__request_cross_device 请用户同意。",
    }
    if trace_id:
        out["trace_id"] = trace_id
    return out


_LOCAL_HOSTS = frozenset({"", "localhost", "127.0.0.1", "::1", "0.0.0.0", "[::1]"})


def nats_url_points_elsewhere(url: str) -> bool:
    """``GALAXY_NATS_URL`` names another machine (not this one).

    Used only to *say* something at startup: a bus pointed at another machine while
    the system is in local mode is a configuration the owner probably did not mean.
    It never changes the mode.
    """
    from urllib.parse import urlsplit

    raw = (url or "").strip()
    if not raw:
        return False
    try:
        host = (urlsplit(raw if "://" in raw else f"nats://{raw}").hostname or "").lower()
    except ValueError:
        return False
    return host not in _LOCAL_HOSTS


def _resolve_network_mode(env: Optional[str]) -> NetworkMode:
    """Parse ``GALAXY_NETWORK_MODE`` into a :class:`NetworkMode`."""
    if env:
        normalized = env.strip().lower()
        try:
            return NetworkMode(normalized)
        except ValueError:
            logger.warning("Unknown GALAXY_NETWORK_MODE=%r; falling back to 'local'", env)
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
    return list(_TRANSPORT_CROSS_DEVICE if mode == SystemMode.DESKTOP_CROSS_DEVICE else _TRANSPORT_LOCAL)


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

    # Cross-device routing is on exactly when the mode is cross-device (one rule).
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
    "cross_device_refusal",
    "cross_device_requested",
    "master_brain_idle_status",
    "master_brain_requested",
    "master_brain_wanted",
    "master_brain_waiting_for_mode",
    "nats_url_points_elsewhere",
    "resolve_fabric_config",
    "FABRIC_CONFIG",
]
