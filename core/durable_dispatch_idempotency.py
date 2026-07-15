#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/durable_dispatch_idempotency.py
====================================
Durable, file-backed **dispatch-side** idempotency for V2 — prevents a
side-effectful node/device action from being executed twice.

Why this exists (distinct from durable_result_idempotency)
----------------------------------------------------------
``core.durable_result_idempotency`` dedups **inbound results** — it stops the
same *result* from being ingested twice on restart/replay. It does NOT stop the
same *action* from being **executed** twice.

NATS worker dispatch is at-least-once: ``nats_bus._subscribe`` acks a message
only *after* the consumer callback runs, and the worker executes the effect
inside that callback (``worker_runtime.execute_dispatch`` → ``invoke_node``).
So if a worker executes an android-tap / desktop-control and then dies before
ack — or the callback raises after the effect — JetStream redelivers the same
dispatch and the effect runs a **second time**. For a system that drives real
devices, a double-tap is a real defect.

This module provides a durable guard that runs **before** the effect executes:

    key = dispatch idempotency key (idempotency_key or task_id)
    if seen(key):  -> short-circuit, do NOT execute again
    else: mark(key) pessimistically, execute; on exception remove(key) so a
          genuine transient failure can be retried.

Semantics (pessimistic, side-effect-safe)
------------------------------------------
- Mark **before** executing → a redelivery never re-runs the effect (we err
  toward "don't double-tap"). This is the correct bias for real-device control.
- A terminal return (success OR node-reported failure) means the effect was
  attempted → the key is kept so further redeliveries stay deduped.
- Only an **exception** from the executor (the effect did not run cleanly)
  rolls the key back, so a fresh delivery can retry.
- Genuine higher-level retries must carry a NEW task_id / idempotency_key;
  redelivery of the SAME dispatch (same key) is what gets deduped.

Not exactly-once
----------------
No purely client-side scheme can be exactly-once for an *external* side effect
(a crash strictly between "effect done" and "mark done" is unobservable). This
closes the dominant, common failure — JetStream redelivery / re-publish — which
is the actual source of double-execution in practice.

Enable / disable
----------------
Active by default; ``GALAXY_DISPATCH_IDEMPOTENCY=0`` disables it (falls back to
the prior always-execute behavior). The guard is a no-op when the dispatch has
no usable key. The whole worker path is itself gated by
``GALAXY_MASTER_BRAIN_ENABLED``, so on a single-machine default this never runs.
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

logger = logging.getLogger("Galaxy.DurableDispatchIdempotency")

_DEFAULT_DISPATCH_ID_STORE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "dispatch_idempotency_set.json",
)

DURABLE_DISPATCH_IDEMPOTENCY_IS_AUTHORITY: str = "DURABLE_DISPATCH_IDEMPOTENCY::FILE_BACKED_PRE_EXECUTE_DEDUP_V1"


def dispatch_idempotency_enabled() -> bool:
    """Whether the dispatch-side guard is active (default on)."""
    return str(os.getenv("GALAXY_DISPATCH_IDEMPOTENCY", "1")).strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


class DurableDispatchIdSet:
    """Thread-safe, file-backed set of dispatch idempotency keys.

    Atomic writes (write-temp-then-rename) so a partial write never corrupts the
    previous good state. Bounded (oldest evicted) to cap disk growth. Lazy load.
    """

    _DEFAULT_MAX = 100_000

    def __init__(self, store_path: Optional[str] = None, *, max_entries: int = _DEFAULT_MAX) -> None:
        self._store_path = store_path or _DEFAULT_DISPATCH_ID_STORE_PATH
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._loaded = False
        self._ids: OrderedDict = OrderedDict()
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self._store_path)), exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("DurableDispatchIdSet: could not create store directory: %s", exc)

    # ------------------------------------------------------------------ API
    def contains(self, key: str) -> bool:
        with self._lock:
            self._ensure_loaded()
            return key in self._ids

    def add(self, key: str) -> bool:
        """Record *key* and durably persist. Returns True if newly added, False if already present."""
        with self._lock:
            self._ensure_loaded()
            if key in self._ids:
                return False
            self._ids[key] = time.time()
            self._evict_if_needed()
            self._flush_locked()
            return True

    def remove(self, key: str) -> bool:
        """Remove *key* (used to roll back a pessimistic mark when the effect threw)."""
        with self._lock:
            self._ensure_loaded()
            if key not in self._ids:
                return False
            del self._ids[key]
            self._flush_locked()
            return True

    def size(self) -> int:
        with self._lock:
            self._ensure_loaded()
            return len(self._ids)

    def clear(self) -> None:
        with self._lock:
            self._ids.clear()
            self._loaded = True
            try:
                if os.path.exists(self._store_path):
                    os.unlink(self._store_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("DurableDispatchIdSet: clear failed to unlink: %s", exc)

    @property
    def store_path(self) -> str:
        return self._store_path

    # ------------------------------------------------------------- internal
    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not os.path.exists(self._store_path):
            return
        try:
            with open(self._store_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            for entry in data.get("dispatch_ids", []):
                if isinstance(entry, list) and len(entry) == 2:
                    self._ids[str(entry[0])] = float(entry[1])
                elif isinstance(entry, str):
                    self._ids[entry] = 0.0
        except Exception as exc:  # noqa: BLE001
            logger.warning("DurableDispatchIdSet: failed to load from %s: %s", self._store_path, exc)

    def _evict_if_needed(self) -> None:
        while len(self._ids) > self._max_entries:
            self._ids.popitem(last=False)

    def _flush_locked(self) -> None:
        try:
            payload = json.dumps(
                {
                    "schema": "dispatch_idempotency_set_v1",
                    "count": len(self._ids),
                    "dispatch_ids": [[k, ts] for k, ts in self._ids.items()],
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
        except Exception as exc:  # noqa: BLE001
            logger.warning("DurableDispatchIdSet: failed to flush to %s: %s", self._store_path, exc)


# --------------------------------------------------------------- singleton
_store_instance: Optional[DurableDispatchIdSet] = None
_store_lock = threading.Lock()


def get_durable_dispatch_id_store(store_path: Optional[str] = None) -> DurableDispatchIdSet:
    """Return (or create) the process-level :class:`DurableDispatchIdSet` singleton."""
    global _store_instance
    if _store_instance is None:
        with _store_lock:
            if _store_instance is None:
                _store_instance = DurableDispatchIdSet(store_path=store_path)
    return _store_instance


def reset_durable_dispatch_id_store() -> None:
    """Reset the process-level singleton (for test isolation)."""
    global _store_instance
    with _store_lock:
        _store_instance = None


# ----------------------------------------------------- convenience helpers
def dispatch_key_for(msg: dict) -> str:
    """Derive the dispatch idempotency key from a dispatch dict.

    Priority: explicit ``idempotency_key`` → ``task_id`` → ``request_id``.
    Returns "" when none present (caller treats as "no guard possible").
    """
    if not isinstance(msg, dict):
        return ""
    for k in ("idempotency_key", "task_id", "request_id"):
        v = msg.get(k)
        if v:
            return str(v)
    return ""


def already_dispatched(key: str) -> bool:
    """True if *key* was already marked as dispatched (should NOT execute again)."""
    return bool(key) and get_durable_dispatch_id_store().contains(key)


def mark_dispatched(key: str) -> bool:
    """Pessimistically mark *key* as dispatched (call BEFORE executing the effect)."""
    if not key:
        return False
    return get_durable_dispatch_id_store().add(key)


def unmark_dispatched(key: str) -> bool:
    """Roll back a mark (call only when the executor raised — effect did not run cleanly)."""
    if not key:
        return False
    return get_durable_dispatch_id_store().remove(key)


__all__ = [
    "DURABLE_DISPATCH_IDEMPOTENCY_IS_AUTHORITY",
    "DurableDispatchIdSet",
    "dispatch_idempotency_enabled",
    "get_durable_dispatch_id_store",
    "reset_durable_dispatch_id_store",
    "dispatch_key_for",
    "already_dispatched",
    "mark_dispatched",
    "unmark_dispatched",
]
