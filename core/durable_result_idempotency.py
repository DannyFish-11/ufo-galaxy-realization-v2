#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/durable_result_idempotency.py
=====================================
Durable, file-backed duplicate result-ID protection for V2.

Background
----------
Prior to this module, result-level idempotency in V2 was purely in-memory.
A V2 process restart, Android reconnect, or replay event could cause a
previously-processed result to be processed a second time, because the
in-memory dedup set was cleared on restart.

This module closes that durability gap by providing:

1. :class:`DurableResultIdSet` — a thread-safe, file-backed set of result
   identifiers that survives V2 process restarts.  Writes are atomic
   (write-then-rename) so a partial write never corrupts the previous
   good state.

2. :func:`get_durable_result_id_store` / :func:`reset_durable_result_id_store`
   — process-level singleton management.

3. :func:`check_result_idempotency` / :func:`record_result_idempotency`
   — the primary convenience API for callers.

Design
------
- **Default-on** — :func:`get_durable_result_id_store` creates the backing
  store automatically, backed by ``data/result_idempotency_set.json``.
- **Atomic writes** — payload written to a temp file then renamed.
- **Bounded** — capped at ``max_entries`` (oldest evicted by insertion order)
  to prevent unbounded disk growth.
- **Standalone** — no dependency on ``pydantic`` or other heavy packages.
- **Thread-safe** — a per-instance :class:`threading.Lock` guards all state.

Sentinels
---------
:data:`DURABLE_RESULT_IDEMPOTENCY_IS_AUTHORITY`
    Confirms this module is the canonical durable duplicate-result
    protection boundary.

Public API
----------
Classes:
    :class:`DurableResultIdSet`

Functions:
    :func:`get_durable_result_id_store`
    :func:`reset_durable_result_id_store`
    :func:`check_result_idempotency`
    :func:`record_result_idempotency`
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from collections import OrderedDict
from typing import Optional

logger = logging.getLogger("Galaxy.DurableResultIdempotency")

# ---------------------------------------------------------------------------
# Default persistence path
# ---------------------------------------------------------------------------

_DEFAULT_RESULT_ID_STORE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "result_idempotency_set.json",
)

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

DURABLE_RESULT_IDEMPOTENCY_IS_AUTHORITY: str = (
    "DURABLE_RESULT_IDEMPOTENCY::FILE_BACKED_RESULT_ID_DEDUP_DEFAULT_ON_V1"
)

# ---------------------------------------------------------------------------
# DurableResultIdSet
# ---------------------------------------------------------------------------


class DurableResultIdSet:
    """Thread-safe, file-backed store for completed result identifiers.

    Persists a set of ``result_id`` strings to a JSON file so that
    duplicate-result protection survives V2 process restarts, reconnects,
    and replays.

    Design
    ------
    * Atomic writes: payload is written to a temp file then renamed so a
      partial write never corrupts the previous good state.
    * Lazy load: the file is read once on the first :meth:`contains` /
      :meth:`add` call; subsequent calls use the in-memory set.
    * Bounded: the set is capped at *max_entries* (oldest evicted by
      insertion-order tracking) to prevent unbounded disk growth.
    * Default-on: :func:`get_durable_result_id_store` creates an instance
      backed by ``data/result_idempotency_set.json`` automatically.

    Parameters
    ----------
    store_path:
        Path to the JSON persistence file.  Defaults to
        ``data/result_idempotency_set.json``.
    max_entries:
        Maximum number of result IDs to retain (oldest evicted first).
        Defaults to 100 000.
    """

    _DEFAULT_MAX = 100_000

    def __init__(
        self,
        store_path: Optional[str] = None,
        *,
        max_entries: int = _DEFAULT_MAX,
    ) -> None:
        self._store_path = store_path or _DEFAULT_RESULT_ID_STORE_PATH
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._loaded = False
        # OrderedDict is used (rather than plain dict) specifically for the
        # popitem(last=False) capability, which efficiently evicts the oldest
        # entry in O(1) when the set exceeds max_entries.
        self._ids: OrderedDict = OrderedDict()
        # Ensure the directory exists
        try:
            os.makedirs(
                os.path.dirname(os.path.abspath(self._store_path)), exist_ok=True
            )
        except Exception as exc:
            logger.warning(
                "DurableResultIdSet: could not create store directory: %s", exc
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def contains(self, result_id: str) -> bool:
        """Return True if *result_id* was previously recorded as seen."""
        with self._lock:
            self._ensure_loaded()
            return result_id in self._ids

    def add(self, result_id: str) -> bool:
        """Record *result_id* as seen and durably persist.

        Returns True if this is the first time the ID is recorded; False
        if it was already present (i.e. duplicate detected).
        """
        with self._lock:
            self._ensure_loaded()
            if result_id in self._ids:
                return False
            self._ids[result_id] = time.time()
            self._evict_if_needed()
            self._flush_locked()
            return True

    def remove(self, result_id: str) -> bool:
        """Remove *result_id* from the durable set (e.g. for test cleanup)."""
        with self._lock:
            self._ensure_loaded()
            if result_id not in self._ids:
                return False
            del self._ids[result_id]
            self._flush_locked()
            return True

    def size(self) -> int:
        """Return the number of stored result IDs."""
        with self._lock:
            self._ensure_loaded()
            return len(self._ids)

    def clear(self) -> None:
        """Remove all result IDs and delete the backing file."""
        with self._lock:
            self._ids.clear()
            self._loaded = True
            try:
                if os.path.exists(self._store_path):
                    os.unlink(self._store_path)
            except Exception as exc:
                logger.warning("DurableResultIdSet: clear failed to unlink: %s", exc)

    @property
    def store_path(self) -> str:
        return self._store_path

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        """Load from disk once (caller must hold self._lock)."""
        if self._loaded:
            return
        self._loaded = True
        if not os.path.exists(self._store_path):
            return
        try:
            with open(self._store_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            raw = data.get("result_ids", [])
            for entry in raw:
                if isinstance(entry, list) and len(entry) == 2:
                    rid, ts = entry
                    self._ids[str(rid)] = float(ts)
                elif isinstance(entry, str):
                    self._ids[entry] = 0.0
            logger.debug(
                "DurableResultIdSet: loaded %d result ids from %s",
                len(self._ids),
                self._store_path,
            )
        except Exception as exc:
            logger.warning(
                "DurableResultIdSet: failed to load from %s: %s",
                self._store_path,
                exc,
            )

    def _evict_if_needed(self) -> None:
        """Evict oldest entries when over cap (caller must hold self._lock)."""
        while len(self._ids) > self._max_entries:
            self._ids.popitem(last=False)

    def _flush_locked(self) -> None:
        """Atomically write current state to disk (caller must hold self._lock)."""
        try:
            payload = json.dumps(
                {
                    "schema": "result_idempotency_set_v1",
                    "count": len(self._ids),
                    "result_ids": [[rid, ts] for rid, ts in self._ids.items()],
                },
                ensure_ascii=False,
            )
            store_dir = os.path.dirname(os.path.abspath(self._store_path))
            fd, tmp_path = tempfile.mkstemp(dir=store_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(payload)
                os.replace(tmp_path, self._store_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception as exc:
            logger.warning(
                "DurableResultIdSet: failed to flush to %s: %s",
                self._store_path,
                exc,
            )


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_store_instance: Optional[DurableResultIdSet] = None
_store_lock = threading.Lock()


def get_durable_result_id_store(
    store_path: Optional[str] = None,
) -> DurableResultIdSet:
    """Return (or create) the process-level :class:`DurableResultIdSet` singleton.

    This is the canonical durable duplicate-result protection boundary.
    Called automatically by :func:`check_result_idempotency` and
    :func:`record_result_idempotency`.

    Parameters
    ----------
    store_path:
        Optional path override.  Respected only before the singleton is
        first created; subsequent calls ignore it.
    """
    global _store_instance
    if _store_instance is None:
        with _store_lock:
            if _store_instance is None:
                _store_instance = DurableResultIdSet(store_path=store_path)
    return _store_instance


def reset_durable_result_id_store() -> None:
    """Reset the process-level singleton (for test isolation)."""
    global _store_instance
    with _store_lock:
        _store_instance = None


# ---------------------------------------------------------------------------
# Convenience helpers — primary integration API
# ---------------------------------------------------------------------------


def check_result_idempotency(result_id: str) -> bool:
    """Return True if *result_id* has already been processed (duplicate).

    Uses the durable file-backed store so duplicate detection survives
    V2 restarts.

    Parameters
    ----------
    result_id:
        The result identifier to check (e.g. from an Android task_result
        or goal_result message).

    Returns
    -------
    bool
        ``True``  — duplicate; caller should suppress processing.
        ``False`` — first time seen; caller should proceed.
    """
    return get_durable_result_id_store().contains(result_id)


def record_result_idempotency(result_id: str) -> bool:
    """Mark *result_id* as processed in the durable store.

    Parameters
    ----------
    result_id:
        The result identifier to record.

    Returns
    -------
    bool
        ``True``  — successfully recorded as new.
        ``False`` — was already present (duplicate).
    """
    return get_durable_result_id_store().add(result_id)


__all__ = [
    "DURABLE_RESULT_IDEMPOTENCY_IS_AUTHORITY",
    "DurableResultIdSet",
    "get_durable_result_id_store",
    "reset_durable_result_id_store",
    "check_result_idempotency",
    "record_result_idempotency",
]
