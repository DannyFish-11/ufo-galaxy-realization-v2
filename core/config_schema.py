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
        # Server / endpoint URLs (non-secret; connection addresses only)
        "endpoints.galaxy_gateway_url",
        "endpoints.android_ws_url",
        "endpoints.nats_url",
        "endpoints.status_board_port",
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

    ENDPOINTS: Dict[str, Any] = {
        "galaxy_gateway_url": "",     # e.g. http://localhost:9000
        "android_ws_url": "",         # e.g. ws://100.x.x.x:8765/ws/device/{device_id}
        "nats_url": "",               # e.g. nats://localhost:4222
        "status_board_port": 8299,    # status board HTTP projection port
    }

    @classmethod
    def as_dict(cls) -> Dict[str, Any]:
        """Return the full default config dict (suitable for runtime/config.json)."""
        return {
            "providers": {k: dict(v) for k, v in cls.PROVIDERS.items()},
            "routing": dict(cls.ROUTING),
            "endpoints": dict(cls.ENDPOINTS),
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
