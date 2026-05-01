"""
core/config_schema.py — Galaxy Unified Local Configuration Schema  (PR-3)
==========================================================================

Defines the canonical schema for ``runtime/config.json`` and
``runtime/secrets.env``.  Provides:

- The list of **known non-secret config keys** (belong in ``runtime/config.json``)
- The list of **known secret keys** (belong in ``runtime/secrets.env`` / env)
- ``ConfigDefaults`` — default values for non-secret config keys
- ``VALID_PROVIDERS`` — recognised provider IDs
- ``VALID_NATIVE_MM_POLICIES`` — accepted multimodal policy values
- ``classify_key(key)`` — returns ``"secret"`` | ``"config"`` | ``"unknown"``

Design contract
---------------
- This module is **data-only** (no I/O, no singleton state).
- It is imported by ``core.config_store``, ``core.config_service``, and
  ``core.config_preflight``.
- Adding a new provider requires updating ``VALID_PROVIDERS`` and
  ``SECRET_KEYS``.
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, Literal

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

CONFIG_SCHEMA_AUTHORITY: str = "ConfigSchema"

# ---------------------------------------------------------------------------
# Recognised provider IDs
# ---------------------------------------------------------------------------

VALID_PROVIDERS: FrozenSet[str] = frozenset(
    {
        "openai",
        "anthropic",
        "gemini",
        "deepseek",
        "groq",
        "openrouter",
        "oneapi",
    }
)

# ---------------------------------------------------------------------------
# Native multimodal policy values
# ---------------------------------------------------------------------------

VALID_NATIVE_MM_POLICIES: FrozenSet[str] = frozenset(
    {
        "strict",       # Only use providers that natively support multimodal
        "prefer",       # Prefer native multimodal; allow fallback
        "allow_fallback",  # Always allow text-only fallback
    }
)

# ---------------------------------------------------------------------------
# Secret key names
# (These belong in runtime/secrets.env or environment variables ONLY.
#  They must NOT appear in runtime/config.json.)
# ---------------------------------------------------------------------------

SECRET_KEYS: FrozenSet[str] = frozenset(
    {
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "DEEPSEEK_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "ONEAPI_API_KEY",
        "GALAXY_API_TOKEN",
        "SECRETVAULT_MASTER_KEY",
    }
)

# Lowercase aliases so callers do not need to normalise
_SECRET_KEYS_LOWER: FrozenSet[str] = frozenset(k.lower() for k in SECRET_KEYS)

# ---------------------------------------------------------------------------
# Non-secret config key paths (dot-notation, canonical in runtime/config.json)
# ---------------------------------------------------------------------------

CONFIG_KEYS: FrozenSet[str] = frozenset(
    {
        # Provider enable/disable flags
        "providers.openai.enabled",
        "providers.anthropic.enabled",
        "providers.gemini.enabled",
        "providers.deepseek.enabled",
        "providers.groq.enabled",
        "providers.openrouter.enabled",
        "providers.oneapi.enabled",
        # OneAPI non-secret metadata
        "providers.oneapi.base_url",
        # Routing preferences
        "routing.native_multimodal_policy",
        "routing.default_provider",
        # Network / endpoint URLs (non-secret — no credentials embedded)
        "network.gateway_url",
        "network.android_gateway_url",
        "network.nats_url",
        "network.ats_url",
        "network.webrtc_stun_url",
        # Android integration settings
        "android.inference_mode",        # "center" | "local" | "hybrid"
        "android.vlm_service_enabled",
    }
)

# ---------------------------------------------------------------------------
# Valid values for network / integration enumerations
# ---------------------------------------------------------------------------

VALID_ANDROID_INFERENCE_MODES: FrozenSet[str] = frozenset(
    {
        "center",   # All inference performed on V2 center via gateway
        "local",    # Inference performed on Android device (requires llama.cpp/NCNN)
        "hybrid",   # Local first, fall back to center on failure
    }
)

# ---------------------------------------------------------------------------
# Default values for runtime/config.json
# ---------------------------------------------------------------------------

class ConfigDefaults:
    """Immutable namespace of default values for non-secret config keys."""

    PROVIDERS: Dict[str, Any] = {
        "openai":     {"enabled": True},
        "anthropic":  {"enabled": False},
        "gemini":     {"enabled": False},
        "deepseek":   {"enabled": False},
        "groq":       {"enabled": False},
        "openrouter": {"enabled": False},
        "oneapi":     {"enabled": False, "base_url": ""},
    }

    ROUTING: Dict[str, Any] = {
        "native_multimodal_policy": "prefer",
        "default_provider": "openai",
    }

    NETWORK: Dict[str, Any] = {
        "gateway_url": "",
        "android_gateway_url": "",
        "nats_url": "",
        "ats_url": "",
        "webrtc_stun_url": "",
    }

    ANDROID: Dict[str, Any] = {
        "inference_mode": "center",
        "vlm_service_enabled": True,
    }

    @classmethod
    def as_dict(cls) -> Dict[str, Any]:
        """Return the full default config dict (suitable for runtime/config.json)."""
        return {
            "providers": {k: dict(v) for k, v in cls.PROVIDERS.items()},
            "routing": dict(cls.ROUTING),
            "network": dict(cls.NETWORK),
            "android": dict(cls.ANDROID),
        }


# ---------------------------------------------------------------------------
# Key classification
# ---------------------------------------------------------------------------

KeyClass = Literal["secret", "config", "unknown"]


def classify_key(key: str) -> KeyClass:
    """
    Classify *key* as ``"secret"``, ``"config"``, or ``"unknown"``.

    Secret keys belong in ``runtime/secrets.env`` or environment variables.
    Config keys belong in ``runtime/config.json``.

    The check is heuristic-based for keys not explicitly listed:
    - Any key whose name (normalised) ends with ``_API_KEY``, ``_TOKEN``,
      ``_SECRET``, or ``_PASSWORD`` is classified as ``"secret"``.
    - The explicit lists take precedence.

    Parameters
    ----------
    key:
        The key name to classify.  May be upper- or lower-case.
    """
    normalised = key.strip()
    upper = normalised.upper()
    lower = normalised.lower()

    # Explicit secret list (exact match)
    if upper in SECRET_KEYS or lower in _SECRET_KEYS_LOWER:
        return "secret"

    # Heuristic: common secret suffixes
    _secret_suffixes = ("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_MASTER_KEY")
    if any(upper.endswith(s) for s in _secret_suffixes):
        return "secret"

    # Explicit config list (exact match, dot-notation)
    if normalised in CONFIG_KEYS or lower in CONFIG_KEYS:
        return "config"

    return "unknown"
