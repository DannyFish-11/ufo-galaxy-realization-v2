#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/unified/capability_resolver.py
=====================================
PR-2 (Block-2) — Unified Capability Resolver

Resolves capability names / queries against the registered contract pool,
applying schema validation before any capability enters the scheduling path.

The resolver acts as a gatekeeper: no capability that fails
:func:`~core.unified.capability_contract.validate_capability_contract`
can be returned by :meth:`CapabilityResolver.resolve`.

Design
------
- Wraps :class:`~core.agent.capability_registry.CapabilityRegistry` (or any
  object with compatible ``list_tools()`` / ``get()`` methods).
- Converts raw :class:`~core.agent.capability_registry.CapabilityItem` entries
  to :class:`~core.unified.capability_contract.CapabilityContract` on the fly
  so callers always receive the unified contract format.
- Caches converted contracts keyed by capability name to avoid repeated
  conversion overhead.

Usage::

    from core.unified.capability_resolver import CapabilityResolver, get_capability_resolver

    resolver = get_capability_resolver()
    contract = resolver.resolve("take_screenshot")   # returns CapabilityContract or None
    contracts = resolver.resolve_all()               # list[CapabilityContract] (valid only)
    resolver.invalidate_cache()                      # force re-read on next resolve
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from .capability_contract import (
    CapabilityContract,
    CapabilityContractError,
    CapabilitySource,
    validate_capability_contract,
)

logger = logging.getLogger("Galaxy.Unified.CapabilityResolver")


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class CapabilityResolver:
    """Resolves capabilities via the unified contract schema.

    Parameters
    ----------
    registry : optional
        Object that exposes ``list_tools()`` and ``get(name)`` methods
        compatible with :class:`~core.agent.capability_registry.CapabilityRegistry`.
        If ``None``, the singleton registry is fetched lazily on first use.
    cache_ttl_seconds : float
        Time in seconds before the resolved-contract cache is invalidated.
        Default is 60 s.
    """

    def __init__(
        self,
        registry: Optional[Any] = None,
        cache_ttl_seconds: float = 60.0,
    ) -> None:
        self._registry = registry
        self._cache_ttl = cache_ttl_seconds
        self._cache: Dict[str, CapabilityContract] = {}
        self._cache_ts: float = 0.0
        self._lock = threading.Lock()
        self._validation_errors: List[Dict[str, Any]] = []

    # ── Registry access ─────────────────────────────────────────────────────

    def _get_registry(self) -> Any:
        if self._registry is not None:
            return self._registry
        try:
            from core.agent.capability_registry import CapabilityRegistry
            return CapabilityRegistry.get_instance()
        except Exception as exc:
            logger.warning("CapabilityResolver: cannot load registry: %s", exc)
            return None

    # ── Cache management ────────────────────────────────────────────────────

    def _is_cache_stale(self) -> bool:
        return (time.time() - self._cache_ts) > self._cache_ttl

    def invalidate_cache(self) -> None:
        """Force the cache to be rebuilt on the next :meth:`resolve` call."""
        with self._lock:
            self._cache.clear()
            self._cache_ts = 0.0

    # ── Conversion ──────────────────────────────────────────────────────────

    @staticmethod
    def _item_to_contract(item: Any) -> CapabilityContract:
        """Convert a :class:`~core.agent.capability_registry.CapabilityItem`
        (or any compatible dict/object) to a :class:`CapabilityContract`."""
        if isinstance(item, CapabilityContract):
            return item

        # Duck-type: accept dataclass, Pydantic model, or plain dict
        if isinstance(item, dict):
            d = item
        else:
            d = {
                "name": getattr(item, "name", ""),
                "description": getattr(item, "description", ""),
                "source": getattr(item, "source", "unknown"),
                "source_id": getattr(item, "source_id", ""),
                "parameters": getattr(item, "parameters", {}),
                "available": getattr(item, "available", True),
                "metadata": getattr(item, "metadata", {}),
            }

        return CapabilityContract.from_dict(d)

    # ── Resolution API ──────────────────────────────────────────────────────

    def _rebuild_cache(self, registry: Any) -> None:
        """Rebuild the in-memory contract cache from *registry*."""
        new_cache: Dict[str, CapabilityContract] = {}
        errors: List[Dict[str, Any]] = []
        items = []
        try:
            items = registry.list_tools() or []
        except Exception as exc:
            logger.warning("CapabilityResolver: list_tools() failed: %s", exc)

        for raw in items:
            try:
                contract = self._item_to_contract(raw)
                validate_capability_contract(contract)
                new_cache[contract.name] = contract
            except CapabilityContractError as exc:
                errors.append({"name": getattr(raw, "name", "?"), "violations": exc.violations})
            except Exception as exc:
                errors.append({"name": getattr(raw, "name", "?"), "error": str(exc)})

        if errors:
            logger.warning(
                "CapabilityResolver: %d capabilities failed contract validation",
                len(errors),
                extra={"event": "capability_resolver_cache_errors", "errors": errors},
            )

        with self._lock:
            self._cache = new_cache
            self._cache_ts = time.time()
            self._validation_errors = errors

        logger.debug(
            "CapabilityResolver: cache rebuilt — %d valid, %d invalid",
            len(new_cache),
            len(errors),
            extra={"event": "capability_resolver_cache_rebuilt", "valid": len(new_cache), "invalid": len(errors)},
        )

    def _ensure_cache(self) -> None:
        """Rebuild cache if stale, or skip if registry unavailable."""
        if not self._is_cache_stale():
            return
        registry = self._get_registry()
        if registry is None:
            return
        self._rebuild_cache(registry)

    def resolve(self, name: str) -> Optional[CapabilityContract]:
        """Return the validated :class:`CapabilityContract` for *name*, or
        ``None`` if not found or failed validation.

        The contract is fetched from the live registry when the cache is stale.
        """
        self._ensure_cache()
        with self._lock:
            cached = self._cache.get(name)
        if cached is not None:
            return cached

        # Fall back to a single-item fetch from the registry (live read)
        registry = self._get_registry()
        if registry is None:
            return None
        raw = None
        try:
            raw = registry.get(name)
        except Exception:
            return None
        if raw is None:
            return None
        try:
            contract = self._item_to_contract(raw)
            validate_capability_contract(contract)
            with self._lock:
                self._cache[name] = contract
            return contract
        except CapabilityContractError:
            return None

    def resolve_all(
        self,
        source: Optional[CapabilitySource] = None,
    ) -> List[CapabilityContract]:
        """Return all validated contracts, optionally filtered by *source*."""
        self._ensure_cache()
        with self._lock:
            contracts = list(self._cache.values())
        if source is not None:
            contracts = [c for c in contracts if c.source == source]
        return contracts

    def resolve_by_tag(self, tag: str) -> List[CapabilityContract]:
        """Return validated contracts whose tags include *tag*."""
        return [c for c in self.resolve_all() if tag in c.tags]

    def find(self, query: str) -> List[CapabilityContract]:
        """Keyword search across name + description of all valid contracts."""
        q = query.lower()
        return [
            c for c in self.resolve_all()
            if q in c.name.lower() or q in c.description.lower()
        ]

    def validation_errors(self) -> List[Dict[str, Any]]:
        """Return the list of contract validation errors from the last cache build."""
        with self._lock:
            return list(self._validation_errors)

    def stats(self) -> Dict[str, Any]:
        """Return resolver statistics for observability."""
        with self._lock:
            return {
                "valid_contracts": len(self._cache),
                "validation_errors": len(self._validation_errors),
                "cache_age_seconds": time.time() - self._cache_ts if self._cache_ts else None,
                "cache_ttl_seconds": self._cache_ttl,
            }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_resolver_instance: Optional[CapabilityResolver] = None
_resolver_lock = threading.Lock()


def get_capability_resolver(registry: Optional[Any] = None) -> CapabilityResolver:
    """Return the process-level :class:`CapabilityResolver` singleton.

    The first call may pass *registry* to inject a custom registry for testing.
    Subsequent calls ignore *registry* unless :func:`reset_capability_resolver`
    is called first.
    """
    global _resolver_instance
    with _resolver_lock:
        if _resolver_instance is None:
            _resolver_instance = CapabilityResolver(registry=registry)
    return _resolver_instance


def reset_capability_resolver() -> None:
    """Destroy the singleton (for testing only)."""
    global _resolver_instance
    with _resolver_lock:
        _resolver_instance = None
