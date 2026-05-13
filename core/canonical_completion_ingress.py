"""core/canonical_completion_ingress.py
========================================
PR-CC: Canonical Completion Ingress — ties Android handoff_result responses to
asyncio.Future objects so OpenClawd can await them instead of relying on
transport-level timeouts.

Design
------
When OpenClawd dispatches an Android handoff it:
  1. Calls ``register_pending_dispatch(handoff_id, task_id)`` → gets back a Future.
  2. Awaits that Future with a timeout.

On the ingress side, ``ingest_android_handoff_response()`` (or any caller) invokes:
  - ``complete_pending_dispatch(handoff_id_or_task_id, envelope)`` → sets Future result.
  - ``notify(envelope)`` → broadcasts to all registered waiters (used by the
    COMPLETION_RESULT_DRIVEN_POLICY hook in android_handoff_v2_response_ingress).

Public API
----------
Class::
    CanonicalCompletionIngress

Functions::
    register_pending_dispatch(handoff_id, task_id) -> asyncio.Future
    complete_pending_dispatch(handoff_id_or_task_id, envelope) -> bool
    get_canonical_completion_ingress() -> CanonicalCompletionIngress
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

CANONICAL_COMPLETION_INGRESS_SENTINEL: str = (
    "CANONICAL_COMPLETION_INGRESS::"
    "core.canonical_completion_ingress::"
    "pr-cc::android-handoff-future-resolution::"
    "result-to-orchestration-closure"
)

FUTURE_RESOLUTION_IS_IDEMPOTENT_POLICY: str = (
    "POLICY::FUTURE_RESOLUTION_IS_IDEMPOTENT: "
    "Calling complete_pending_dispatch for an already-resolved or missing Future "
    "MUST be safe and silently ignored (no exception raised)."
)

NOTIFY_BROADCASTS_TO_ALL_TERMINAL_WAITERS_POLICY: str = (
    "POLICY::NOTIFY_BROADCASTS_TO_ALL_TERMINAL_WAITERS: "
    "notify() matches by handoff_id first, then task_id, and resolves any "
    "registered Future.  Non-terminal envelopes (ack) do NOT resolve the Future."
)

DUPLICATE_REGISTRATION_CANCELS_ORPHAN_POLICY: str = (
    "POLICY::DUPLICATE_REGISTRATION_CANCELS_ORPHAN: "
    "If register_pending_dispatch is called with a handoff_id or task_id that "
    "already has a pending (not-done) Future registered, the existing Future is "
    "cancelled before the new Future is stored.  This prevents silent orphaning "
    "of the first waiter in retry/re-dispatch scenarios.  Callers that register "
    "the same key twice MUST be aware that the first awaiter will receive a "
    "CancelledError."
)

IS_TERMINAL_ATTRIBUTE_ERROR_POLICY: str = (
    "POLICY::IS_TERMINAL_ATTRIBUTE_ERROR: "
    "In notify(), if envelope.is_terminal raises AttributeError (attribute absent) "
    "the envelope is treated as terminal per original design intent.  If it raises "
    "any other exception (broken property, runtime error) the envelope is treated as "
    "non-terminal and notify() returns False without resolving any Future.  "
    "This prevents a malformed envelope from prematurely closing a dispatch Future."
)


# ---------------------------------------------------------------------------
# CanonicalCompletionIngress
# ---------------------------------------------------------------------------


class CanonicalCompletionIngress:
    """Ties Android handoff responses to asyncio.Future objects.

    Thread-safe: internal state is protected by a threading.Lock.
    Futures are created in the event loop of the registering coroutine.

    Registry layout
    ---------------
    ``_futures_by_handoff_id`` : Dict[str, asyncio.Future]
    ``_futures_by_task_id``    : Dict[str, asyncio.Future]  (fallback index)
    """

    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._futures_by_handoff_id: Dict[str, asyncio.Future] = {}
        self._futures_by_task_id: Dict[str, asyncio.Future] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_pending_dispatch(
        self,
        handoff_id: str,
        task_id: Optional[str] = None,
    ) -> "asyncio.Future[Any]":
        """Register a pending handoff dispatch and return an awaitable Future.

        Parameters
        ----------
        handoff_id:
            Primary correlation key (from HandoffEnvelopeV2).
        task_id:
            Optional fallback correlation key.

        Returns
        -------
        asyncio.Future
            The caller should await this Future (with a timeout) to receive
            the terminal AndroidHandoffResponseEnvelope.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop: fall back to get_event_loop() which may return the
            # default loop or create one.  Callers in sync context are responsible
            # for setting the event loop before registering dispatches.
            loop = asyncio.get_event_loop()

        fut: asyncio.Future = loop.create_future()

        with self._lock:
            if handoff_id:
                existing = self._futures_by_handoff_id.get(handoff_id)
                if existing is not None and not existing.done():
                    logger.warning(
                        "canonical_completion_ingress: duplicate registration for "
                        "handoff_id=%r — cancelling orphaned previous Future to "
                        "prevent silent hang. See DUPLICATE_REGISTRATION_CANCELS_ORPHAN_POLICY.",
                        handoff_id,
                    )
                    try:
                        existing.cancel()
                    except Exception as _cancel_exc:
                        logger.debug(
                            "canonical_completion_ingress: cancel() raised for "
                            "handoff_id=%r: %s",
                            handoff_id,
                            _cancel_exc,
                        )
                self._futures_by_handoff_id[handoff_id] = fut
                logger.debug(
                    "canonical_completion_ingress: registered handoff_id=%r", handoff_id
                )
            if task_id:
                existing_tid = self._futures_by_task_id.get(task_id)
                if existing_tid is not None and not existing_tid.done():
                    logger.warning(
                        "canonical_completion_ingress: duplicate registration for "
                        "task_id=%r — cancelling orphaned previous Future. "
                        "See DUPLICATE_REGISTRATION_CANCELS_ORPHAN_POLICY.",
                        task_id,
                    )
                    try:
                        existing_tid.cancel()
                    except Exception as _cancel_exc:
                        logger.debug(
                            "canonical_completion_ingress: cancel() raised for "
                            "task_id=%r: %s",
                            task_id,
                            _cancel_exc,
                        )
                self._futures_by_task_id[task_id] = fut
                logger.debug(
                    "canonical_completion_ingress: registered task_id=%r", task_id
                )

        return fut

    # ------------------------------------------------------------------
    # Resolution helpers
    # ------------------------------------------------------------------

    def complete_pending_dispatch(
        self,
        handoff_id_or_task_id: str,
        envelope: Any,
    ) -> bool:
        """Resolve the Future registered under *handoff_id_or_task_id*.

        Tries ``handoff_id`` index first, then ``task_id`` index.

        Parameters
        ----------
        handoff_id_or_task_id:
            The correlation key used when the dispatch was registered.
        envelope:
            The terminal response envelope to set as the Future result.

        Returns
        -------
        bool
            True if a pending Future was found and resolved; False otherwise.
        """
        return self._resolve_key(handoff_id_or_task_id, envelope, clear=True)

    def notify(self, envelope: Any) -> bool:
        """Broadcast a terminal response envelope to any registered awaiter.

        Used by the ``COMPLETION_RESULT_DRIVEN_POLICY`` hook so that
        *all* terminal handoff results reach registered Futures, even when
        the caller does not know which index was used for registration.

        Ack responses (``is_terminal == False``) do NOT resolve the Future.

        Parameters
        ----------
        envelope:
            An ``AndroidHandoffResponseEnvelope`` (or duck-typed equivalent).

        Returns
        -------
        bool
            True if a Future was found and resolved.
        """
        # Only resolve for terminal responses.
        try:
            is_terminal_flag = envelope.is_terminal
        except AttributeError:
            # Attribute absent → treat as terminal per original design intent.
            is_terminal_flag = True
        except Exception as exc:
            # Unexpected error accessing is_terminal (broken property, etc.).
            # Default to non-terminal for safety: do not resolve a Future based
            # on a malformed envelope.  See IS_TERMINAL_ATTRIBUTE_ERROR_POLICY.
            logger.debug(
                "canonical_completion_ingress: unexpected error reading is_terminal "
                "from kind=%s: %s — treating as non-terminal for safety",
                getattr(envelope, "response_kind", "?"),
                exc,
            )
            return False
        if not is_terminal_flag:
            logger.debug(
                "canonical_completion_ingress: notify skipped (non-terminal kind=%s)",
                getattr(envelope, "response_kind", "?"),
            )
            return False

        handoff_id = getattr(envelope, "handoff_id", None) or ""
        task_id = getattr(envelope, "task_id", None) or ""
        problem_closed_signal = bool(
            getattr(envelope, "problem_closed", False)
            or getattr(envelope, "final_answer_ready", False)
            or getattr(envelope, "problem_solved", False)
            or getattr(envelope, "final_user_response", "")
        )

        resolved = False
        if handoff_id:
            resolved = self._resolve_key(handoff_id, envelope, clear=True)
        if not resolved and task_id:
            resolved = self._resolve_key(task_id, envelope, clear=True)

        if resolved:
            logger.info(
                "canonical_completion_ingress: notify resolved handoff_id=%r task_id=%r kind=%s problem_closed_signal=%s",
                handoff_id,
                task_id,
                getattr(envelope, "response_kind", "?"),
                problem_closed_signal,
            )
        else:
            logger.debug(
                "canonical_completion_ingress: notify miss handoff_id=%r "
                "task_id=%r",
                handoff_id,
                task_id,
            )
        return resolved

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_key(self, key: str, envelope: Any, *, clear: bool) -> bool:
        """Resolve the Future indexed by *key* (checks both indices).

        Returns True if a Future was found and set.
        """
        fut: Optional[asyncio.Future] = None

        with self._lock:
            if key in self._futures_by_handoff_id:
                fut = self._futures_by_handoff_id[key]
                if clear:
                    del self._futures_by_handoff_id[key]
                    # Also clean up task_id cross-index if present
                    task_id = getattr(envelope, "task_id", None) or ""
                    self._futures_by_task_id.pop(task_id, None)
            elif key in self._futures_by_task_id:
                fut = self._futures_by_task_id[key]
                if clear:
                    del self._futures_by_task_id[key]
                    handoff_id = getattr(envelope, "handoff_id", None) or ""
                    self._futures_by_handoff_id.pop(handoff_id, None)

        if fut is None:
            return False

        if fut.done():
            logger.debug(
                "canonical_completion_ingress: Future already resolved for key=%r", key
            )
            return False

        try:
            fut.set_result(envelope)
            return True
        except asyncio.InvalidStateError:
            logger.debug(
                "canonical_completion_ingress: InvalidStateError resolving key=%r "
                "(race condition, already resolved)",
                key,
            )
            return False
        except Exception as exc:
            logger.warning(
                "canonical_completion_ingress: unexpected error resolving key=%r: %s",
                key,
                exc,
            )
            return False

    def fail_pending_dispatch(
        self,
        handoff_id_or_task_id: str,
        exc: BaseException,
    ) -> bool:
        """Resolve the Future registered under *handoff_id_or_task_id* with *exc*.

        Unlike :meth:`complete_pending_dispatch` (which calls
        ``Future.set_result``), this method calls ``Future.set_exception`` so
        that ``await future`` raises *exc* on the awaiting side.  This is used
        by the restart recovery coordinator to unblock stale waiters with an
        explicit restart error rather than leaving them hanging indefinitely.

        Parameters
        ----------
        handoff_id_or_task_id:
            The correlation key used when the dispatch was registered.
        exc:
            The exception to raise at the awaiting call site.

        Returns
        -------
        bool
            True if a pending Future was found and resolved; False otherwise.
        """
        return self._fail_key(handoff_id_or_task_id, exc, clear=True)

    def _fail_key(self, key: str, exc: BaseException, *, clear: bool) -> bool:
        """Resolve the Future indexed by *key* with *exc* via ``set_exception``.

        Returns True if a Future was found and set.
        """
        fut: Optional[asyncio.Future] = None

        with self._lock:
            if key in self._futures_by_handoff_id:
                fut = self._futures_by_handoff_id[key]
                if clear:
                    del self._futures_by_handoff_id[key]
            elif key in self._futures_by_task_id:
                fut = self._futures_by_task_id[key]
                if clear:
                    del self._futures_by_task_id[key]

        if fut is None:
            return False

        if fut.done():
            logger.debug(
                "canonical_completion_ingress: Future already resolved for key=%r "
                "(fail_key no-op)",
                key,
            )
            return False

        try:
            fut.set_exception(exc)
            return True
        except asyncio.InvalidStateError:
            logger.debug(
                "canonical_completion_ingress: InvalidStateError failing key=%r "
                "(race condition, already resolved)",
                key,
            )
            return False
        except Exception as err:
            logger.warning(
                "canonical_completion_ingress: unexpected error failing key=%r: %s",
                key,
                err,
            )
            return False

    def pending_count(self) -> int:
        """Return the number of pending (unresolved) dispatches."""
        with self._lock:
            return len(self._futures_by_handoff_id)


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_singleton: Optional[CanonicalCompletionIngress] = None
_singleton_lock: threading.Lock = threading.Lock()


def get_canonical_completion_ingress() -> CanonicalCompletionIngress:
    """Return the process-level singleton :class:`CanonicalCompletionIngress`.

    Thread-safe double-checked locking.  Tests that require isolation should
    construct a fresh :class:`CanonicalCompletionIngress` directly.
    """
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = CanonicalCompletionIngress()
    return _singleton


# ---------------------------------------------------------------------------
# Module-level convenience wrappers
# ---------------------------------------------------------------------------


def register_pending_dispatch(
    handoff_id: str,
    task_id: Optional[str] = None,
) -> "asyncio.Future[Any]":
    """Module-level shortcut: ``get_canonical_completion_ingress().register_pending_dispatch(...)``."""
    return get_canonical_completion_ingress().register_pending_dispatch(
        handoff_id, task_id
    )


def complete_pending_dispatch(
    handoff_id_or_task_id: str,
    envelope: Any,
) -> bool:
    """Module-level shortcut: ``get_canonical_completion_ingress().complete_pending_dispatch(...)``."""
    return get_canonical_completion_ingress().complete_pending_dispatch(
        handoff_id_or_task_id, envelope
    )


def fail_pending_dispatch(
    handoff_id_or_task_id: str,
    exc: BaseException,
) -> bool:
    """Module-level shortcut: ``get_canonical_completion_ingress().fail_pending_dispatch(...)``."""
    return get_canonical_completion_ingress().fail_pending_dispatch(
        handoff_id_or_task_id, exc
    )


__all__ = [
    # Sentinels
    "CANONICAL_COMPLETION_INGRESS_SENTINEL",
    "FUTURE_RESOLUTION_IS_IDEMPOTENT_POLICY",
    "NOTIFY_BROADCASTS_TO_ALL_TERMINAL_WAITERS_POLICY",
    "DUPLICATE_REGISTRATION_CANCELS_ORPHAN_POLICY",
    "IS_TERMINAL_ATTRIBUTE_ERROR_POLICY",
    # Class
    "CanonicalCompletionIngress",
    # Singleton factory
    "get_canonical_completion_ingress",
    # Module-level shortcuts
    "register_pending_dispatch",
    "complete_pending_dispatch",
    "fail_pending_dispatch",
]
