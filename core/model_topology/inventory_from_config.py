"""
core/model_topology/inventory_from_config.py
=============================================
Builds a :class:`~core.model_topology.provider_inventory.ProviderInventory`
whose entries have config-authority-driven participation flags
(:attr:`~core.model_topology.provider_inventory.ProviderInventoryEntry.config_enabled`,
:attr:`~core.model_topology.provider_inventory.ProviderInventoryEntry.config_has_key`).

This module is the **wiring layer** between the unified local configuration
authority (``core.config_service.ConfigService``) and the provider inventory /
routing candidate-pool formation path introduced by PR-4.

Architecture
------------

::

    ConfigService (config authority)
          │
          ▼
    build_inventory_from_config_authority()
          │
          ▼
    ProviderInventory   ←─ entries tagged with config_enabled / config_has_key
          │
          ├─ candidate_pool_entries()   ← routing inputs (enabled + has key)
          ├─ disabled_entries()         ← diagnostic view
          └─ unconfigured_entries()     ← diagnostic view (enabled, missing key)

PR-4 objectives satisfied here
-------------------------------
1. ProviderInventory construction now consumes the unified config authority.
2. Provider enable/disable state is reflected in runtime inventory.
3. Active routing candidate-pool formation excludes disabled/unconfigured
   providers (via ``ProviderInventory.candidate_pool_entries()``).
4. Unconfigured OneAPI is treated as **absent** from the candidate pool.
5. Configured OneAPI can participate (lower-horizon semantics preserved).

Public API
----------
INVENTORY_CONFIG_AUTHORITY
    Authority sentinel for this module.

build_inventory_from_config_authority(config_service=None) -> ProviderInventory
    Construct a ProviderInventory whose entries reflect the persisted config.
    Entries are created from ``ConfigService.get_provider_statuses()`` and
    wrapped as minimal ``ProviderInventoryEntry`` objects.  Pass an existing
    ``ProviderInventory`` to ``merge_config_authority_into_inventory()``
    if you have a richer pre-built inventory that you want to tag with
    config-authority flags instead.

merge_config_authority_into_inventory(inventory, config_service=None) -> ProviderInventory
    Apply config-authority ``config_enabled`` / ``config_has_key`` flags to
    the entries of an *existing* ``ProviderInventory`` (built e.g. by
    ``ConfigBridge.build_inventory``).  Returns the same inventory object
    with entries mutated in-place.

build_candidate_pool(inventory) -> list[ProviderInventoryEntry]
    Convenience alias for ``inventory.candidate_pool_entries()``.

get_oneapi_candidate_state(config_service=None) -> str
    Return ``"configured"`` | ``"partial"`` | ``"absent"`` for OneAPI,
    consumed by downstream diagnostics / preflight output.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from .provider_inventory import ProviderInventory, ProviderInventoryEntry
from .topology_types import (
    AvailabilityStatus,
    ModalityCapability,
    ModelIdentity,
    NormalizedTopologyEntry,
    ProviderCategory,
    ProviderIdentity,
    ScoringProfile,
    TopologyRole,
)

logger = logging.getLogger("Galaxy.ModelTopology.InventoryFromConfig")

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

INVENTORY_CONFIG_AUTHORITY: str = (
    "core.model_topology.inventory_from_config.InventoryFromConfig"
)

# ---------------------------------------------------------------------------
# Provider-level metadata defaults
# (Used to produce minimal NormalizedTopologyEntry objects from config state.)
# ---------------------------------------------------------------------------

# Default primary model IDs per provider (used when no richer inventory exists).
_PROVIDER_DEFAULT_MODEL: dict = {
    "openai":     "gpt-4o",
    "anthropic":  "claude-3-5-sonnet-20241022",
    "gemini":     "gemini-1.5-pro",
    "deepseek":   "deepseek-chat",
    "groq":       "llama-3.1-70b-versatile",
    "openrouter": "openrouter/auto",
    "oneapi":     "oneapi-aggregated",
}

# Default display names per provider.
_PROVIDER_DISPLAY_NAME: dict = {
    "openai":     "OpenAI",
    "anthropic":  "Anthropic",
    "gemini":     "Google Gemini",
    "deepseek":   "DeepSeek",
    "groq":       "Groq",
    "openrouter": "OpenRouter",
    "oneapi":     "OneAPI Aggregator",
}

# Providers that natively support multimodal input.
_NATIVE_MULTIMODAL_PROVIDERS: frozenset = frozenset({"openai", "anthropic", "gemini"})

# Scoring profiles (speed, quality) per provider — approximate defaults.
_PROVIDER_SCORING: dict = {
    "openai":     (8, 10),
    "anthropic":  (7, 10),
    "gemini":     (8, 9),
    "deepseek":   (7, 8),
    "groq":       (10, 7),
    "openrouter": (6, 7),
    "oneapi":     (5, 6),
}

# Category per provider.
_PROVIDER_CATEGORY: dict = {
    "openai":     ProviderCategory.DIRECT,
    "anthropic":  ProviderCategory.DIRECT,
    "gemini":     ProviderCategory.DIRECT,
    "deepseek":   ProviderCategory.DIRECT,
    "groq":       ProviderCategory.DIRECT,
    "openrouter": ProviderCategory.DIRECT,
    "oneapi":     ProviderCategory.ONEAPI,
}

# Role hints per provider.
_PROVIDER_ROLE_HINTS: dict = {
    "openai":     [TopologyRole.MULTIMODAL_CORE, TopologyRole.GENERAL],
    "anthropic":  [TopologyRole.MULTIMODAL_CORE, TopologyRole.REASONING],
    "gemini":     [TopologyRole.MULTIMODAL_CORE, TopologyRole.GENERAL],
    "deepseek":   [TopologyRole.REASONING, TopologyRole.GENERAL],
    "groq":       [TopologyRole.EXECUTION, TopologyRole.GENERAL],
    "openrouter": [TopologyRole.GENERAL],
    "oneapi":     [TopologyRole.ROUTING],
}

# API key env-var name per provider (mirrors config_service._PROVIDER_KEY_MAP).
_PROVIDER_ENV_KEY: dict = {
    "openai":     "OPENAI_API_KEY",
    "anthropic":  "ANTHROPIC_API_KEY",
    "gemini":     "GEMINI_API_KEY",
    "deepseek":   "DEEPSEEK_API_KEY",
    "groq":       "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "oneapi":     "ONEAPI_API_KEY",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_minimal_entry(
    provider_id: str,
    has_key: bool,
    config_enabled: bool,
    config_has_key: bool,
) -> ProviderInventoryEntry:
    """Construct a minimal ``ProviderInventoryEntry`` from config-authority data.

    This is used when no richer inventory (built by ``ConfigBridge``) is
    available.  The resulting entry carries all required topology fields at
    sensible defaults so that routing and diagnostics code can consume it
    without special-casing.
    """
    multimodal = provider_id in _NATIVE_MULTIMODAL_PROVIDERS
    speed, quality = _PROVIDER_SCORING.get(provider_id, (5, 5))
    env_key = _PROVIDER_ENV_KEY.get(provider_id)

    normalized = NormalizedTopologyEntry(
        provider=ProviderIdentity(
            provider_id=provider_id,
            display_name=_PROVIDER_DISPLAY_NAME.get(provider_id, provider_id),
        ),
        model=ModelIdentity(
            model_id=_PROVIDER_DEFAULT_MODEL.get(provider_id, f"{provider_id}-default"),
            provider_id=provider_id,
        ),
        modality=ModalityCapability.from_multimodal_flag(multimodal),
        scoring=ScoringProfile(speed_score=speed, quality_score=quality),
        availability=AvailabilityStatus(
            available=has_key,
            missing_env_key=env_key if not has_key else None,
            all_env_keys=[env_key] if env_key else [],
        ),
        category=_PROVIDER_CATEGORY.get(provider_id, ProviderCategory.UNKNOWN),
        role_hints=list(_PROVIDER_ROLE_HINTS.get(provider_id, [TopologyRole.GENERAL])),
    )
    return ProviderInventoryEntry(
        entry=normalized,
        config_enabled=config_enabled,
        config_has_key=config_has_key,
        config_source="config_authority",
    )


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_inventory_from_config_authority(
    config_service=None,
) -> ProviderInventory:
    """Build a ``ProviderInventory`` driven by the unified config authority.

    Each entry's ``config_enabled`` and ``config_has_key`` fields reflect the
    persisted state in ``runtime/config.json`` and ``runtime/secrets.env``
    (merged with environment-variable overrides, per ``ConfigService``
    priority rules).

    OneAPI semantics (PR-4 requirement)
    ------------------------------------
    - If the unified config authority reports ``oneapi_state == "absent"``,
      the OneAPI entry is included in the inventory (for diagnostic visibility)
      but ``config_enabled`` and ``config_has_key`` are both set to ``False``,
      so it will **not** appear in ``candidate_pool_entries()``.
    - If ``oneapi_state == "configured"``, OneAPI enters the inventory as
      candidate-eligible.
    - If ``oneapi_state == "partial"``, OneAPI is enabled but missing config;
      ``config_enabled=True``, ``config_has_key=False`` — shows in
      ``unconfigured_entries()`` only.

    Parameters
    ----------
    config_service:
        Optional ``ConfigService`` instance.  When ``None``, the global
        singleton is used.  Provide a custom instance in tests.

    Returns
    -------
    ProviderInventory
        Inventory with config-authority-driven participation flags.
    """
    if config_service is None:
        from core.config_service import get_config_service
        config_service = get_config_service()

    validation = config_service.validate()
    oneapi_state = validation.oneapi_state  # "configured" | "partial" | "absent"

    entries: List[ProviderInventoryEntry] = []

    for pstatus in validation.provider_statuses:
        pid = pstatus.provider_id
        if pid == "oneapi":
            # OneAPI uses separate absent/configured semantics
            if oneapi_state == "absent":
                # Absent: included for diagnostic visibility only; not eligible
                inv_entry = _make_minimal_entry(
                    provider_id=pid,
                    has_key=False,
                    config_enabled=False,
                    config_has_key=False,
                )
            elif oneapi_state == "configured":
                inv_entry = _make_minimal_entry(
                    provider_id=pid,
                    has_key=True,
                    config_enabled=True,
                    config_has_key=True,
                )
            else:
                # "partial": enabled but missing base_url or key
                inv_entry = _make_minimal_entry(
                    provider_id=pid,
                    has_key=False,
                    config_enabled=True,
                    config_has_key=False,
                )
        else:
            inv_entry = _make_minimal_entry(
                provider_id=pid,
                has_key=pstatus.has_key,
                config_enabled=pstatus.enabled,
                config_has_key=pstatus.has_key,
            )
        entries.append(inv_entry)

    inventory = ProviderInventory(entries=entries)
    logger.info(
        "build_inventory_from_config_authority: %s",
        inventory,
    )
    return inventory


def merge_config_authority_into_inventory(
    inventory: ProviderInventory,
    config_service=None,
) -> ProviderInventory:
    """Apply config-authority flags to an *existing* ``ProviderInventory``.

    Use this when you have a richer inventory (built by ``ConfigBridge`` from
    dashboard-era snapshots) and want to overlay the unified config authority's
    enable/disable and key-presence state without discarding the richer
    topology metadata.

    For each entry in *inventory* whose ``provider_id`` is known to the config
    authority, the entry's ``config_enabled``, ``config_has_key``, and
    ``config_source`` fields are updated in-place.

    Entries whose ``provider_id`` is not recognised by the config authority are
    left unchanged (``config_source`` stays ``"unknown"``).

    OneAPI semantics: same absent/configured/partial rules as
    :func:`build_inventory_from_config_authority`.

    Parameters
    ----------
    inventory:
        An existing ``ProviderInventory`` to annotate.
    config_service:
        Optional ``ConfigService`` instance.

    Returns
    -------
    ProviderInventory
        The same *inventory* object, entries updated in-place.
    """
    if config_service is None:
        from core.config_service import get_config_service
        config_service = get_config_service()

    validation = config_service.validate()
    oneapi_state = validation.oneapi_state

    # Build a quick lookup from provider_id → ProviderStatus
    status_map = {ps.provider_id: ps for ps in validation.provider_statuses}

    for inv_entry in inventory.all_entries():
        pid = inv_entry.provider_id
        if pid == "oneapi":
            if oneapi_state == "absent":
                inv_entry.config_enabled = False
                inv_entry.config_has_key = False
            elif oneapi_state == "configured":
                inv_entry.config_enabled = True
                inv_entry.config_has_key = True
            else:
                # partial
                inv_entry.config_enabled = True
                inv_entry.config_has_key = False
            inv_entry.config_source = "config_authority"
        elif pid in status_map:
            pstatus = status_map[pid]
            inv_entry.config_enabled = pstatus.enabled
            inv_entry.config_has_key = pstatus.has_key
            inv_entry.config_source = "config_authority"
        # else: leave config_source = "unknown"

    logger.info(
        "merge_config_authority_into_inventory: %s",
        inventory,
    )
    return inventory


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def build_candidate_pool(
    inventory: ProviderInventory,
) -> List[ProviderInventoryEntry]:
    """Return the routing candidate pool from *inventory*.

    This is a thin convenience alias for
    :meth:`~core.model_topology.provider_inventory.ProviderInventory.candidate_pool_entries`.

    Only entries where both ``config_enabled`` and ``config_has_key`` are
    ``True`` are returned.  This is the set of providers eligible to appear
    in routing candidate consideration.

    Disabled providers and providers missing required secrets are excluded.

    Parameters
    ----------
    inventory:
        A ``ProviderInventory`` (ideally one that has had config-authority
        flags applied).

    Returns
    -------
    list[ProviderInventoryEntry]
    """
    return inventory.candidate_pool_entries()


def get_oneapi_candidate_state(config_service=None) -> str:
    """Return the OneAPI candidate state from the config authority.

    Returns
    -------
    str
        ``"configured"`` — OneAPI is fully configured and may participate
        in the candidate pool (lower-horizon semantics).

        ``"partial"`` — OneAPI is enabled in config but is missing required
        secrets or base_url; shown in diagnostics as unconfigured.

        ``"absent"`` — OneAPI is not configured; treated as absent from the
        candidate pool.  This is the default when no config is present.
    """
    if config_service is None:
        from core.config_service import get_config_service
        config_service = get_config_service()
    return config_service.validate().oneapi_state
