"""
core.cognitive.cognitive_field_engine — Continuous Cognitive Field Engine
=========================================================================

Provides :class:`CognitiveFieldEngine`: a background asyncio task that
**ticks** the cognitive state periodically — even when no new requests arrive
— so the system maintains a continuous cognitive loop rather than waking only
on discrete events.

Tick behaviour
--------------
Each tick:

1. Applies natural momentum decay to ``manifest_pressure`` and ``activation``.
2. Increases ``stability`` slightly (field settles when undisturbed).
3. Decreases ``stability`` when recent rapid updates are detected.
4. Emits a ``cognitive.tick`` event on the
   :mod:`~core.state_event_bus` for observability.
5. Calls registered per-tick listeners (sync or async).

Configuration (``config.json``)
--------------------------------
- ``enable_cognitive_field_engine`` (bool, default ``true``) — master switch.
- ``cognitive_field_tick_interval_s`` (float, default ``5.0``) — seconds between ticks.

Usage::

    from core.cognitive.cognitive_field_engine import get_cognitive_field_engine

    engine = get_cognitive_field_engine()
    await engine.start()        # starts the background loop
    engine.notify_request()     # call on every incoming request
    await engine.stop()         # graceful shutdown
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Union

from core.cognitive.continuous_state import CognitiveState, get_cognitive_state

logger = logging.getLogger("Galaxy.Cognitive.Engine")

# ---------------------------------------------------------------------------
# State event bus constant — added in Block-3 (best-effort import)
# ---------------------------------------------------------------------------

_COGNITIVE_TICK_EVENT = "cognitive.tick"
_COGNITIVE_REQUEST_EVENT = "cognitive.request"


def _emit_cognitive_event(event_type: str, payload: Dict[str, Any], trace_id: str = "") -> None:
    """Best-effort emission on the unified state event bus."""
    try:
        from core.state_event_bus import get_state_event_bus

        bus = get_state_event_bus()
        # Publish as a raw string event type (the bus accepts str)
        bus.publish(
            event_type,
            source="cognitive_field_engine",
            payload=payload,
            trace_id=trace_id or f"cfe_{int(time.time()*1000)%10**9}",
        )
    except Exception as exc:
        logger.debug("cognitive event emission failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class CognitiveFieldEngine:
    """Background cognitive field engine.

    Ticks the :class:`~core.cognitive.continuous_state.CognitiveState` at a
    configurable interval, ensuring continuous cognition even when the system
    is idle.

    Parameters
    ----------
    state:
        The :class:`~core.cognitive.continuous_state.CognitiveState` instance
        to update.  Defaults to the process-wide singleton.
    tick_interval_s:
        Seconds between ticks.  Reads from ``config.json`` key
        ``cognitive_field_tick_interval_s`` if not given explicitly.
    enabled:
        When *False* the engine starts but immediately skips all ticking.
        Reads from ``config.json`` key ``enable_cognitive_field_engine``.
    """

    def __init__(
        self,
        state: Optional[CognitiveState] = None,
        tick_interval_s: Optional[float] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        self._state = state or get_cognitive_state()
        self._tick_interval_s = tick_interval_s or self._read_config_tick_interval()
        self._enabled = enabled if enabled is not None else self._read_config_enabled()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._tick_count = 0
        self._last_request_ts: float = 0.0
        self._listeners: List[Callable] = []
        self._lock = threading.Lock()
        logger.debug(
            "CognitiveFieldEngine init | enabled=%s tick_interval_s=%.1f",
            self._enabled,
            self._tick_interval_s,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background tick loop.

        Safe to call multiple times; subsequent calls are no-ops.
        """
        if self._running:
            return
        self._running = True
        if self._enabled:
            self._task = asyncio.ensure_future(self._tick_loop())
            logger.info(
                "CognitiveFieldEngine started | tick_interval_s=%.1f",
                self._tick_interval_s,
            )
        else:
            logger.info("CognitiveFieldEngine disabled — tick loop not started")

    async def stop(self) -> None:
        """Stop the background tick loop gracefully."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("CognitiveFieldEngine stopped after %d ticks", self._tick_count)

    def notify_request(
        self,
        *,
        intent_delta: float = 0.3,
        activation_delta: float = 0.2,
        uncertainty: Optional[float] = None,
        trace_id: str = "",
    ) -> None:
        """Notify the engine that a new request has arrived.

        Applies an input signal to the cognitive state and emits a
        ``cognitive.request`` event.  This method is synchronous and
        thread-safe so it can be called from any context.

        Parameters
        ----------
        intent_delta:
            Increase in intent strength from this request.
        activation_delta:
            Increase in activation from this request.
        uncertainty:
            Optional override for uncertainty (e.g. based on LLM confidence).
        trace_id:
            Correlation ID for event tracing.
        """
        self._last_request_ts = time.time()
        self._state.apply_input(
            intent_delta=intent_delta,
            activation_delta=activation_delta,
            uncertainty_override=uncertainty,
        )
        snap = self._state.snapshot()
        _emit_cognitive_event(_COGNITIVE_REQUEST_EVENT, snap, trace_id=trace_id)
        logger.debug(
            "CognitiveFieldEngine.notify_request | activation=%.3f intent=%.3f pressure=%.3f",
            snap["activation"],
            snap["intent_strength"],
            snap["manifest_pressure"],
        )

    def notify_task_complete(
        self,
        *,
        task_id: str = "",
        trace_id: str = "",
    ) -> None:
        """Notify the engine that a task has completed.

        Triggers the decay controller to begin the manifest→liminal→passive
        reabsorption sequence.  This is the integration point with
        :class:`~core.cognitive.decay_controller.DecayController`.
        """
        try:
            from core.cognitive.decay_controller import get_decay_controller

            get_decay_controller().trigger_decay(task_id=task_id, trace_id=trace_id)
        except Exception as exc:
            logger.debug("notify_task_complete decay trigger failed (non-fatal): %s", exc)

    def add_tick_listener(self, listener: Callable) -> None:
        """Register a callable that is invoked on every tick.

        The listener receives a single argument: the cognitive state snapshot
        dict.  Sync and async callables are both supported.
        """
        with self._lock:
            self._listeners.append(listener)

    def remove_tick_listener(self, listener: Callable) -> None:
        """Deregister a previously registered tick listener."""
        with self._lock:
            self._listeners = [l for l in self._listeners if l != listener]

    @property
    def tick_count(self) -> int:
        """Total number of ticks executed since the engine was started."""
        return self._tick_count

    # ------------------------------------------------------------------
    # Internal tick logic
    # ------------------------------------------------------------------

    async def _tick_loop(self) -> None:
        """Background coroutine running the tick at the configured interval."""
        while self._running:
            await asyncio.sleep(self._tick_interval_s)
            if not self._running:
                break
            try:
                await self._do_tick()
            except Exception as exc:
                logger.warning("CognitiveFieldEngine tick error (non-fatal): %s", exc)

    async def _do_tick(self) -> None:
        """Perform a single cognitive tick."""
        self._tick_count += 1
        now = time.time()
        idle_s = now - self._last_request_ts if self._last_request_ts > 0 else float("inf")

        snap_before = self._state.snapshot()

        # Natural relaxation: decay manifest_pressure and activation toward rest
        mp = snap_before["manifest_pressure"]
        act = snap_before["activation"]
        dr = snap_before["decay_rate"]
        stab = snap_before["stability"]

        # Decay is faster when idle
        effective_decay = dr * (1.5 if idle_s > 30 else 1.0)
        new_mp = max(0.0, mp - effective_decay * mp)
        new_act = max(0.0, act - effective_decay * 0.5 * act)

        # Stability recovers during idle ticks
        new_stab = min(1.0, stab + 0.02) if idle_s > 10 else stab

        self._state.update(
            manifest_pressure=new_mp,
            activation=new_act,
            stability=new_stab,
        )

        snap = self._state.snapshot()
        snap["tick_count"] = self._tick_count
        snap["idle_s"] = round(idle_s, 1)

        _emit_cognitive_event(_COGNITIVE_TICK_EVENT, snap)

        logger.debug(
            "CognitiveFieldEngine tick #%d | activation=%.3f intent=%.3f pressure=%.3f stab=%.3f idle_s=%.0f",
            self._tick_count,
            snap["activation"],
            snap["intent_strength"],
            snap["manifest_pressure"],
            snap["stability"],
            idle_s,
        )

        # Dispatch tick listeners
        listeners = []
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                result = listener(snap)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.debug("tick listener error (non-fatal): %s", exc)

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_config_tick_interval() -> float:
        try:
            import json
            import pathlib

            cfg = json.loads(
                (
                    pathlib.Path(__file__).parents[2] / "config.json"
                ).read_text()
            )
            return float(cfg.get("cognitive_field_tick_interval_s", 5.0))
        except Exception:
            return 5.0

    @staticmethod
    def _read_config_enabled() -> bool:
        try:
            import json
            import pathlib

            cfg = json.loads(
                (
                    pathlib.Path(__file__).parents[2] / "config.json"
                ).read_text()
            )
            return bool(cfg.get("enable_cognitive_field_engine", True))
        except Exception:
            return True


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_engine_instance: Optional[CognitiveFieldEngine] = None
_engine_lock = threading.Lock()


def get_cognitive_field_engine() -> CognitiveFieldEngine:
    """Return the process-wide :class:`CognitiveFieldEngine` singleton."""
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = CognitiveFieldEngine()
                logger.debug("CognitiveFieldEngine singleton initialised")
    return _engine_instance


def reset_cognitive_field_engine() -> None:
    """Reset the singleton (for testing only)."""
    global _engine_instance
    with _engine_lock:
        _engine_instance = None
