"""
core/config_service.py — Galaxy Unified Local Configuration Service  (PR-3)
============================================================================

High-level API for reading and writing to the local unified configuration
authority (``runtime/config.json`` and ``runtime/secrets.env``).

This layer is intended to be called by:
- ``windows_client/status_board_v2`` in a future interactive config-entry PR
- CLI / setup tooling that needs to provision secrets or toggle providers
- ``core.config_preflight`` for structured validation

Public API
----------
ConfigService
    The main service class.  Construct via ``get_config_service()`` for the
    global singleton or instantiate directly for testing.

ConfigValidationResult
    Structured result returned by ``validate()``.

get_config_service() -> ConfigService
    Return (and lazily create) the process-level singleton.

reset_config_service()
    Reset the singleton (primarily for tests).

Design notes
------------
- All write operations are delegated to ``core.config_store.ConfigStore``.
- Validation delegates to ``core.config_preflight.run_preflight`` so that
  there is a single validation path in the system.
- The service is **not** responsible for schema migration — that belongs in
  future PRs.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config_schema import (
    CONFIG_SCHEMA_AUTHORITY,
    VALID_NATIVE_MM_POLICIES,
    VALID_PROVIDERS,
    ConfigDefaults,
    classify_key,
)
from core.config_store import ConfigStore, get_config_store

logger = logging.getLogger("Galaxy.ConfigService")

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

CONFIG_SERVICE_AUTHORITY: str = "ConfigService"

# ---------------------------------------------------------------------------
# Provider → env-var key mapping
# ---------------------------------------------------------------------------

_PROVIDER_KEY_MAP: Dict[str, str] = {
    "openai":     "OPENAI_API_KEY",
    "anthropic":  "ANTHROPIC_API_KEY",
    "gemini":     "GEMINI_API_KEY",
    "deepseek":   "DEEPSEEK_API_KEY",
    "groq":       "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "oneapi":     "ONEAPI_API_KEY",
}

# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

@dataclass
class ProviderStatus:
    """Status of a single provider from the configuration service perspective."""
    provider_id: str
    enabled: bool
    has_key: bool

    @property
    def ready(self) -> bool:
        """True when the provider is enabled and has an API key configured."""
        return self.enabled and self.has_key

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "enabled": self.enabled,
            "has_key": self.has_key,
            "ready": self.ready,
        }


@dataclass
class ConfigValidationResult:
    """
    Structured result returned by ``ConfigService.validate()``.

    Attributes
    ----------
    ok:
        True when there are no CRITICAL issues.
    missing_secrets:
        Secrets that are required by enabled providers but absent.
    invalid_values:
        Mapping of key → description for malformed/invalid config values.
    provider_statuses:
        Per-provider readiness breakdown.
    oneapi_state:
        ``"configured"`` | ``"absent"`` — OneAPI aggregator state.
    warnings:
        Non-blocking issues (warnings from preflight or logic checks).
    """
    ok: bool = True
    missing_secrets: List[str] = field(default_factory=list)
    invalid_values: Dict[str, str] = field(default_factory=dict)
    provider_statuses: List[ProviderStatus] = field(default_factory=list)
    oneapi_state: str = "absent"
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "missing_secrets": self.missing_secrets,
            "invalid_values": self.invalid_values,
            "provider_statuses": [p.to_dict() for p in self.provider_statuses],
            "oneapi_state": self.oneapi_state,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class ConfigService:
    """
    High-level configuration service for the local unified authority.

    Parameters
    ----------
    store:
        A ``ConfigStore`` instance.  Defaults to the global singleton.
    """

    def __init__(self, store: Optional[ConfigStore] = None) -> None:
        self._store = store or get_config_store()

    # ------------------------------------------------------------------
    # Secret writes
    # ------------------------------------------------------------------

    def set_secret(self, key: str, value: str) -> None:
        """
        Store a secret *key* in ``runtime/secrets.env``.

        The key must be classifiable as a secret (see ``config_schema``).
        Raises ``core.config_store.NonSecretInSecretsError`` if the key is
        a known non-secret config value.

        Parameters
        ----------
        key:
            The env-var name (e.g. ``"OPENAI_API_KEY"``).
        value:
            The secret value.  Must be non-empty.
        """
        if not value or not value.strip():
            raise ValueError(f"Secret value for '{key}' must be non-empty.")
        self._store.write_secret(key, value)
        logger.info("Secret written: %s", key)

    def set_provider_api_key(self, provider: str, api_key: str) -> None:
        """
        Store the API key for *provider* in ``runtime/secrets.env``.

        Parameters
        ----------
        provider:
            One of ``VALID_PROVIDERS`` (e.g. ``"openai"``).
        api_key:
            The provider's API key.
        """
        provider = provider.lower().strip()
        if provider not in VALID_PROVIDERS:
            raise ValueError(
                f"Unknown provider '{provider}'. "
                f"Valid providers: {sorted(VALID_PROVIDERS)}"
            )
        env_key = _PROVIDER_KEY_MAP.get(provider)
        if not env_key:
            raise ValueError(f"No API key mapping defined for provider '{provider}'.")
        self.set_secret(env_key, api_key)

    def set_oneapi(self, base_url: str, api_key: str) -> None:
        """
        Configure the OneAPI aggregator (lower-horizon position).

        Writes:
        - ``providers.oneapi.base_url`` → ``runtime/config.json``
        - ``ONEAPI_API_KEY`` → ``runtime/secrets.env``

        Also enables the ``oneapi`` provider in ``runtime/config.json``.

        Parameters
        ----------
        base_url:
            HTTP(S) URL of the OneAPI endpoint.
        api_key:
            OneAPI API key.
        """
        if not base_url or not base_url.strip():
            raise ValueError("OneAPI base_url must be non-empty.")
        # Write non-secret config
        config = self._store.read_config()
        providers = config.get("providers", {})
        if not isinstance(providers, dict):
            providers = {}
        if "oneapi" not in providers:
            providers["oneapi"] = {}
        providers["oneapi"]["base_url"] = base_url.strip()
        providers["oneapi"]["enabled"] = True
        config["providers"] = providers
        self._store.write_config(config)
        # Write secret
        self.set_secret("ONEAPI_API_KEY", api_key)
        logger.info("OneAPI configured: base_url=%s", base_url)

    # ------------------------------------------------------------------
    # Non-secret config writes
    # ------------------------------------------------------------------

    def set_toggle(self, provider: str, enabled: bool) -> None:
        """
        Enable or disable a *provider* in ``runtime/config.json``.

        Parameters
        ----------
        provider:
            One of ``VALID_PROVIDERS``.
        enabled:
            ``True`` to enable, ``False`` to disable.
        """
        provider = provider.lower().strip()
        if provider not in VALID_PROVIDERS:
            raise ValueError(
                f"Unknown provider '{provider}'. "
                f"Valid providers: {sorted(VALID_PROVIDERS)}"
            )
        config = self._store.read_config()
        providers = config.get("providers", {})
        if not isinstance(providers, dict):
            providers = {}
        if provider not in providers:
            providers[provider] = {}
        providers[provider]["enabled"] = bool(enabled)
        config["providers"] = providers
        self._store.write_config(config)
        logger.info("Provider toggle: %s → %s", provider, enabled)

    def set_native_mm_policy(self, mode: str) -> None:
        """
        Set the native multimodal routing policy in ``runtime/config.json``.

        Parameters
        ----------
        mode:
            One of ``VALID_NATIVE_MM_POLICIES``:
            ``"strict"`` | ``"prefer"`` | ``"allow_fallback"``.
        """
        mode = mode.strip()
        if mode not in VALID_NATIVE_MM_POLICIES:
            raise ValueError(
                f"Invalid native_multimodal_policy '{mode}'. "
                f"Valid values: {sorted(VALID_NATIVE_MM_POLICIES)}"
            )
        config = self._store.read_config()
        routing = config.get("routing", {})
        if not isinstance(routing, dict):
            routing = {}
        routing["native_multimodal_policy"] = mode
        config["routing"] = routing
        self._store.write_config(config)
        logger.info("native_multimodal_policy → %s", mode)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> ConfigValidationResult:
        """
        Validate the effective configuration and return a structured result.

        Checks:
        - Each enabled provider has a corresponding API key available
          (from env-var or ``runtime/secrets.env``).
        - ``routing.native_multimodal_policy`` is a valid value.
        - OneAPI: ``base_url`` is present when enabled.

        Returns
        -------
        ConfigValidationResult
        """
        result = ConfigValidationResult()

        config = self._store.read_config()
        providers_cfg = config.get("providers", {})
        if not isinstance(providers_cfg, dict):
            providers_cfg = {}
        routing_cfg = config.get("routing", {})
        if not isinstance(routing_cfg, dict):
            routing_cfg = {}

        # ── Provider checks ──────────────────────────────────────────
        for provider_id in sorted(VALID_PROVIDERS):
            p_cfg = providers_cfg.get(provider_id, {})
            if not isinstance(p_cfg, dict):
                p_cfg = {}
            enabled = bool(p_cfg.get("enabled", ConfigDefaults.PROVIDERS.get(provider_id, {}).get("enabled", False)))
            env_key = _PROVIDER_KEY_MAP.get(provider_id)
            has_key = False
            if env_key:
                has_key = bool(self._store.get_secret(env_key))
            pstatus = ProviderStatus(
                provider_id=provider_id,
                enabled=enabled,
                has_key=has_key,
            )
            result.provider_statuses.append(pstatus)
            if enabled and not has_key:
                result.missing_secrets.append(env_key or f"{provider_id.upper()}_API_KEY")

        # ── OneAPI state ─────────────────────────────────────────────
        oneapi_cfg = providers_cfg.get("oneapi", {})
        if not isinstance(oneapi_cfg, dict):
            oneapi_cfg = {}
        oneapi_enabled = bool(oneapi_cfg.get("enabled", False))
        oneapi_key = self._store.get_secret("ONEAPI_API_KEY")
        oneapi_base_url = oneapi_cfg.get("base_url", "")
        if oneapi_enabled and oneapi_key and oneapi_base_url:
            result.oneapi_state = "configured"
        elif oneapi_enabled:
            result.oneapi_state = "partial"
            if not oneapi_key:
                if "ONEAPI_API_KEY" not in result.missing_secrets:
                    result.missing_secrets.append("ONEAPI_API_KEY")
            if not oneapi_base_url:
                result.invalid_values["providers.oneapi.base_url"] = (
                    "OneAPI is enabled but base_url is empty."
                )
        else:
            result.oneapi_state = "absent"

        # ── Routing policy check ─────────────────────────────────────
        policy = routing_cfg.get("native_multimodal_policy", "")
        if policy and policy not in VALID_NATIVE_MM_POLICIES:
            result.invalid_values["routing.native_multimodal_policy"] = (
                f"Invalid value '{policy}'. "
                f"Expected one of: {sorted(VALID_NATIVE_MM_POLICIES)}"
            )

        # ── Summary ──────────────────────────────────────────────────
        result.ok = (
            len(result.missing_secrets) == 0
            and len(result.invalid_values) == 0
        )
        return result

    def describe_missing(self) -> str:
        """
        Return a human-readable summary of missing or misconfigured items.

        Intended for CLI output and status-board display.
        """
        v = self.validate()
        lines = []
        if v.missing_secrets:
            lines.append("Missing secrets:")
            for s in v.missing_secrets:
                lines.append(f"  • {s}")
        if v.invalid_values:
            lines.append("Invalid config values:")
            for k, msg in v.invalid_values.items():
                lines.append(f"  • {k}: {msg}")
        disabled = [
            p.provider_id for p in v.provider_statuses
            if not p.enabled
        ]
        if disabled:
            lines.append(f"Disabled providers: {', '.join(disabled)}")
        unavailable = [
            p.provider_id for p in v.provider_statuses
            if p.enabled and not p.has_key
        ]
        if unavailable:
            lines.append(
                f"Enabled but key missing: {', '.join(unavailable)}"
            )
        lines.append(f"OneAPI state: {v.oneapi_state}")
        if not lines:
            return "Configuration OK — all enabled providers have keys."
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def get_provider_statuses(self) -> List[ProviderStatus]:
        """Return a list of ``ProviderStatus`` for all known providers."""
        return self.validate().provider_statuses

    def is_provider_ready(self, provider: str) -> bool:
        """
        Return ``True`` if *provider* is enabled and has an API key.
        """
        provider = provider.lower().strip()
        for p in self.get_provider_statuses():
            if p.provider_id == provider:
                return p.ready
        return False


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_singleton: Optional[ConfigService] = None
_singleton_lock = threading.Lock()


def get_config_service() -> ConfigService:
    """Return the process-level ``ConfigService`` singleton."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = ConfigService()
    return _singleton


def reset_config_service() -> None:
    """Reset the singleton (for tests)."""
    global _singleton
    with _singleton_lock:
        _singleton = None
