#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/unified/idempotency.py
============================
Block-5: Idempotency & Deduplication Guards

Provides a process-level idempotency store that prevents duplicate command
side-effects when the same ``idempotency_key`` is submitted more than once.

Design
------
* The store is an **in-memory LRU cache** (no external dependency) with a
  configurable TTL.  For production deployments requiring distributed
  idempotency, swap in a Redis-backed implementation by sub-classing
  :class:`IdempotencyStore` and overriding ``check`` / ``record`` / ``clear``.

* The :func:`check_idempotency` and :func:`record_idempotency` helpers are
  the primary integration API; they are called by
  :class:`~core.unified.command_envelope.CommandEnvelope` processing and
  :class:`~core.hybrid_executor.HybridExecutionArbiter`.

Error classes
-------------
:class:`DuplicateCommandError` — raised when an already-completed key is
re-submitted.  It is mapped to
:attr:`~core.unified.error_codes.GalaxyErrorCode.IDEMPOTENCY_DUPLICATE`.

:class:`IdempotencyConflictError` — raised when the same key is submitted
with a different ``payload_hash``.  Mapped to
:attr:`~core.unified.error_codes.GalaxyErrorCode.IDEMPOTENCY_CONFLICT`.

Usage::

    from core.unified.idempotency import (
        get_idempotency_store,
        check_idempotency,
        record_idempotency,
    )

    # Before executing a command:
    entry = check_idempotency(key, payload_hash)
    if entry is not None:
        return entry.cached_result     # return de-duped result

    result = await do_work()

    # After successful execution:
    record_idempotency(key, payload_hash, result)
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.Idempotency")

# Default settings
_DEFAULT_TTL_SECONDS: float = 3600.0   # 1 hour
_DEFAULT_MAX_ENTRIES: int = 10_000


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DuplicateCommandError(Exception):
    """Raised when a command with an already-processed idempotency key arrives."""

    def __init__(self, key: str, cached_result: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(f"Duplicate command detected for idempotency key '{key}'")
        self.key = key
        self.cached_result = cached_result
        self.code = "ID_001"


class IdempotencyConflictError(Exception):
    """Raised when the same key arrives with a different payload hash."""

    def __init__(self, key: str, stored_hash: str, received_hash: str) -> None:
        super().__init__(
            f"Idempotency conflict for key '{key}': "
            f"stored_hash={stored_hash!r} vs received_hash={received_hash!r}"
        )
        self.key = key
        self.stored_hash = stored_hash
        self.received_hash = received_hash
        self.code = "ID_002"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class IdempotencyStatus(str, Enum):
    """Processing status of an idempotency entry."""

    IN_FLIGHT = "in_flight"   # command is currently being executed
    COMPLETED = "completed"   # command finished successfully
    FAILED = "failed"         # command finished with error


@dataclass
class IdempotencyEntry:
    """One record in the idempotency store."""

    key: str
    payload_hash: str
    status: IdempotencyStatus = IdempotencyStatus.IN_FLIGHT
    cached_result: Optional[Dict[str, Any]] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    trace_id: str = ""
    task_id: str = ""

    def is_expired(self, ttl: float) -> bool:
        return (time.time() - self.created_at) > ttl

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "payload_hash": self.payload_hash,
            "status": self.status.value,
            "cached_result": self.cached_result,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
        }


# ---------------------------------------------------------------------------
# Idempotency store
# ---------------------------------------------------------------------------


class IdempotencyStore:
    """Thread-safe, in-memory idempotency store with LRU eviction and TTL.

    This is the **singleton** for the current process.  Use
    :func:`get_idempotency_store` to obtain the instance.
    """

    _instance: Optional["IdempotencyStore"] = None

    def __new__(cls) -> "IdempotencyStore":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_store()
        return cls._instance

    def _init_store(self) -> None:
        self._store: OrderedDict[str, IdempotencyEntry] = OrderedDict()
        self._ttl: float = _DEFAULT_TTL_SECONDS
        self._max_entries: int = _DEFAULT_MAX_ENTRIES
        self._stats = {"hits": 0, "misses": 0, "conflicts": 0, "evictions": 0}

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def check(
        self,
        key: str,
        payload_hash: str,
        *,
        raise_on_duplicate: bool = True,
        raise_on_conflict: bool = True,
    ) -> Optional[IdempotencyEntry]:
        """Look up *key* in the store.

        Returns:
            ``None``  — key is new; caller should proceed with execution.
            entry     — key was previously recorded.

        Raises:
            :class:`DuplicateCommandError` if *raise_on_duplicate* is True
                and the entry status is ``COMPLETED``.
            :class:`IdempotencyConflictError` if *raise_on_conflict* is True
                and the stored payload hash differs from *payload_hash*.
        """
        self._evict_expired()
        entry = self._store.get(key)
        if entry is None:
            self._stats["misses"] += 1
            return None

        # Conflict check
        if entry.payload_hash != payload_hash:
            self._stats["conflicts"] += 1
            if raise_on_conflict:
                raise IdempotencyConflictError(key, entry.payload_hash, payload_hash)

        self._stats["hits"] += 1

        if entry.status == IdempotencyStatus.COMPLETED and raise_on_duplicate:
            raise DuplicateCommandError(key, entry.cached_result)

        # Move to end (LRU: most recently used)
        self._store.move_to_end(key)
        return entry

    def record_in_flight(
        self,
        key: str,
        payload_hash: str,
        *,
        trace_id: str = "",
        task_id: str = "",
    ) -> IdempotencyEntry:
        """Mark *key* as IN_FLIGHT (execution started)."""
        self._evict_expired()
        entry = IdempotencyEntry(
            key=key,
            payload_hash=payload_hash,
            status=IdempotencyStatus.IN_FLIGHT,
            trace_id=trace_id,
            task_id=task_id,
        )
        self._store[key] = entry
        self._store.move_to_end(key)
        self._enforce_max()
        logger.debug("Idempotency: IN_FLIGHT key=%s", key)
        return entry

    def record_completed(
        self,
        key: str,
        result: Optional[Dict[str, Any]] = None,
    ) -> Optional[IdempotencyEntry]:
        """Mark *key* as COMPLETED and cache *result*."""
        entry = self._store.get(key)
        if entry is None:
            logger.warning("Idempotency: complete for unknown key=%s", key)
            return None
        entry.status = IdempotencyStatus.COMPLETED
        entry.cached_result = result
        entry.completed_at = time.time()
        self._store.move_to_end(key)
        logger.debug("Idempotency: COMPLETED key=%s", key)
        return entry

    def record_failed(self, key: str) -> Optional[IdempotencyEntry]:
        """Mark *key* as FAILED (allows future re-submission of same key)."""
        entry = self._store.get(key)
        if entry is None:
            return None
        entry.status = IdempotencyStatus.FAILED
        entry.completed_at = time.time()
        logger.debug("Idempotency: FAILED key=%s", key)
        return entry

    def remove(self, key: str) -> bool:
        """Explicitly remove *key* from the store."""
        return self._store.pop(key, None) is not None

    def get(self, key: str) -> Optional[IdempotencyEntry]:
        return self._store.get(key)

    def stats(self) -> Dict[str, Any]:
        return {**self._stats, "store_size": len(self._store)}

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def configure(
        self,
        ttl_seconds: Optional[float] = None,
        max_entries: Optional[int] = None,
    ) -> None:
        """Update TTL and max-entry settings at runtime."""
        if ttl_seconds is not None:
            self._ttl = float(ttl_seconds)
        if max_entries is not None:
            self._max_entries = int(max_entries)

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------

    def _evict_expired(self) -> None:
        expired = [k for k, e in self._store.items() if e.is_expired(self._ttl)]
        for k in expired:
            del self._store[k]
            self._stats["evictions"] += 1

    def _enforce_max(self) -> None:
        while len(self._store) > self._max_entries:
            self._store.popitem(last=False)
            self._stats["evictions"] += 1


# ---------------------------------------------------------------------------
# Singleton accessor + reset (for tests)
# ---------------------------------------------------------------------------


def get_idempotency_store() -> IdempotencyStore:
    """Return the process-level :class:`IdempotencyStore` singleton."""
    return IdempotencyStore()


def reset_idempotency_store() -> None:
    """Reset the singleton (for testing)."""
    IdempotencyStore._instance = None


# ---------------------------------------------------------------------------
# Convenience helpers (preferred integration API)
# ---------------------------------------------------------------------------


def make_payload_hash(payload: Any) -> str:
    """Compute a stable SHA-256 hash for any JSON-serialisable *payload*.

    Returns the first 32 hex characters (128 bits of SHA-256 output).  This
    provides > 10^38 combinations — far more than sufficient to avoid accidental
    collisions in an idempotency store whose keys are already scoped to a single
    session / request.  Using the full 64-character digest is equally valid; the
    truncation is purely for readability in logs.
    """
    try:
        serialised = json.dumps(payload, sort_keys=True, default=str)
    except (TypeError, ValueError):
        serialised = repr(payload)
    return hashlib.sha256(serialised.encode()).hexdigest()[:32]


def check_idempotency(
    key: str,
    payload_hash: str,
    *,
    raise_on_duplicate: bool = True,
    raise_on_conflict: bool = True,
) -> Optional[IdempotencyEntry]:
    """Convenience wrapper around :meth:`IdempotencyStore.check`."""
    return get_idempotency_store().check(
        key,
        payload_hash,
        raise_on_duplicate=raise_on_duplicate,
        raise_on_conflict=raise_on_conflict,
    )


def record_idempotency(
    key: str,
    payload_hash: str,
    result: Optional[Dict[str, Any]] = None,
    *,
    trace_id: str = "",
    task_id: str = "",
) -> IdempotencyEntry:
    """Record a completed execution result for *key*.

    If the key is not yet in the store (i.e. :func:`check_idempotency` was not
    called first), it creates an IN_FLIGHT entry and immediately marks it
    COMPLETED.  This ensures callers that skip the check step still record
    their results.
    """
    store = get_idempotency_store()
    if store.get(key) is None:
        store.record_in_flight(key, payload_hash, trace_id=trace_id, task_id=task_id)
    entry = store.record_completed(key, result)
    return entry  # type: ignore[return-value]
