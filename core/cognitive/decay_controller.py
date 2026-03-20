"""
core.cognitive.decay_controller — Post-manifest Decay & Reabsorption
=====================================================================

Handles the **manifest → liminal → passive** decay sequence after a task
completes, ensuring the system smoothly reabsorbs back to a quiet state
rather than hard-resetting or remaining "stuck" in the manifest region.

Decay model
-----------
After a task completion event the controller schedules a configurable sequence
of decay steps applied to the
:class:`~core.cognitive.continuous_state.CognitiveState`:

1. **Manifest → Liminal** — ``manifest_pressure`` and ``activation`` decay
   rapidly toward the liminal threshold.
2. **Liminal → Passive** — slower natural decay continues until both fields
   drop below the passive threshold.

Each step emits a ``cognitive.decay`` event on the state event bus so the
decay process is **fully observable**.

Task lifecycle integration
--------------------------
The controller subscribes to :class:`~core.state_event_bus.StateEventType`
``TASK_DONE`` and ``TASK_FAILED`` events so that decay is triggered
automatically when tasks complete.  Manual triggering is also possible via
:meth:`trigger_decay`.

Configuration (``config.json``)
--------------------------------
- ``cognitive_decay_rate``           (float 0–1, default ``0.10``) — fractional
  decay per step (overrides ``CognitiveState.decay_rate``).
- ``cognitive_decay_step_interval_s`` (float, default ``0.5``) — seconds between
  decay steps.
- ``cognitive_decay_steps``          (int, default ``8``) — number of steps in
  the full decay sequence.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Dict, Optional

from core.cognitive.continuous_state import CognitiveState, get_cognitive_state

logger = logging.getLogger("Galaxy.Cognitive.Decay")

_COGNITIVE_DECAY_EVENT = "cognitive.decay"


def _emit_decay_event(payload: Dict[str, Any], trace_id: str = "") -> None:
    """Best-effort emission of a decay event on the state event bus."""
    try:
        from core.state_event_bus import get_state_event_bus

        get_state_event_bus().publish(
            _COGNITIVE_DECAY_EVENT,
            source="decay_controller",
            payload=payload,
            trace_id=trace_id or f"decay_{int(time.time()*1000)%10**9}",
        )
    except Exception as exc:
        logger.debug("decay event emission failed (non-fatal): %s", exc)


class DecayController:
    """Controls post-manifest cognitive decay and reabsorption.

    Parameters
    ----------
    state:
        :class:`~core.cognitive.continuous_state.CognitiveState` to decay.
        Defaults to the process-wide singleton.
    decay_rate:
        Fractional decay per step (0–1).  Overrides the state's own
        ``decay_rate`` when provided explicitly.
    step_interval_s:
        Seconds between individual decay steps.
    num_steps:
        Total number of decay steps before decay sequence ends.
    """

    def __init__(
        self,
        state: Optional[CognitiveState] = None,
        decay_rate: Optional[float] = None,
        step_interval_s: Optional[float] = None,
        num_steps: Optional[int] = None,
    ) -> None:
        self._state = state or get_cognitive_state()
        cfg = self._read_config()
        self._decay_rate = decay_rate if decay_rate is not None else float(
            cfg.get("cognitive_decay_rate", 0.10)
        )
        self._step_interval_s = step_interval_s if step_interval_s is not None else float(
            cfg.get("cognitive_decay_step_interval_s", 0.5)
        )
        self._num_steps = num_steps if num_steps is not None else int(
            cfg.get("cognitive_decay_steps", 8)
        )
        self._active_decay_task: Optional[asyncio.Task] = None
        self._subscribed = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def subscribe_to_task_lifecycle(self) -> None:
        """Subscribe to the state event bus to auto-trigger decay on task completion.

        Idempotent — subsequent calls are no-ops.
        """
        if self._subscribed:
            return
        try:
            from core.state_event_bus import get_state_event_bus, StateEventType

            bus = get_state_event_bus()
            bus.subscribe(StateEventType.TASK_DONE, self._on_task_done)
            bus.subscribe(StateEventType.TASK_FAILED, self._on_task_done)
            self._subscribed = True
            logger.debug("DecayController subscribed to TASK_DONE / TASK_FAILED events")
        except Exception as exc:
            logger.warning("DecayController.subscribe_to_task_lifecycle failed (non-fatal): %s", exc)

    def trigger_decay(self, *, task_id: str = "", trace_id: str = "") -> None:
        """Manually trigger the decay sequence.

        Safe to call from sync code.  Schedules the async decay loop if a
        running event loop is available; otherwise runs a synchronous
        single-step decay fallback.

        Parameters
        ----------
        task_id:
            Optional task identifier for trace correlation.
        trace_id:
            Correlation ID for event tracing.
        """
        logger.info(
            "DecayController.trigger_decay | task_id=%s trace_id=%s",
            task_id,
            trace_id,
        )
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._async_decay_sequence(task_id=task_id, trace_id=trace_id))
        except RuntimeError:
            # No running event loop — apply a single synchronous decay step
            self._sync_decay_step(task_id=task_id, trace_id=trace_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _on_task_done(self, event: Any) -> None:
        """State event bus subscriber callback for task completion."""
        task_id = ""
        trace_id = ""
        try:
            payload = getattr(event, "payload", {}) or {}
            task_id = str(payload.get("task_id", ""))
            trace_id = getattr(event, "trace_id", "") or ""
        except Exception:
            pass
        self.trigger_decay(task_id=task_id, trace_id=trace_id)

    async def _async_decay_sequence(self, *, task_id: str, trace_id: str) -> None:
        """Run the full multi-step decay sequence asynchronously."""
        for step in range(self._num_steps):
            snap = self._state.snapshot()
            mp = snap["manifest_pressure"]
            act = snap["activation"]

            # Stop early if already fully decayed
            if mp < 0.01 and act < 0.01:
                logger.debug("DecayController: fully decayed after %d steps", step + 1)
                break

            new_mp = max(0.0, mp * (1.0 - self._decay_rate))
            new_act = max(0.0, act * (1.0 - self._decay_rate * 0.7))
            new_stability = min(1.0, snap["stability"] + 0.03)

            self._state.update(
                manifest_pressure=new_mp,
                activation=new_act,
                stability=new_stability,
            )

            _emit_decay_event(
                {
                    "step": step + 1,
                    "total_steps": self._num_steps,
                    "manifest_pressure_before": round(mp, 4),
                    "manifest_pressure_after": round(new_mp, 4),
                    "activation_before": round(act, 4),
                    "activation_after": round(new_act, 4),
                    "task_id": task_id,
                },
                trace_id=trace_id,
            )
            logger.debug(
                "DecayController step %d/%d | pressure %.3f→%.3f activation %.3f→%.3f task_id=%s",
                step + 1,
                self._num_steps,
                mp,
                new_mp,
                act,
                new_act,
                task_id,
            )
            await asyncio.sleep(self._step_interval_s)

    def _sync_decay_step(self, *, task_id: str, trace_id: str) -> None:
        """Single synchronous decay step (fallback when no event loop is running)."""
        snap = self._state.snapshot()
        mp = snap["manifest_pressure"]
        act = snap["activation"]
        new_mp = max(0.0, mp * (1.0 - self._decay_rate))
        new_act = max(0.0, act * (1.0 - self._decay_rate * 0.7))
        self._state.update(
            manifest_pressure=new_mp,
            activation=new_act,
            stability=min(1.0, snap["stability"] + 0.03),
        )
        _emit_decay_event(
            {
                "step": 1,
                "total_steps": 1,
                "manifest_pressure_before": round(mp, 4),
                "manifest_pressure_after": round(new_mp, 4),
                "activation_before": round(act, 4),
                "activation_after": round(new_act, 4),
                "task_id": task_id,
                "sync_fallback": True,
            },
            trace_id=trace_id,
        )
        logger.debug(
            "DecayController sync step | pressure %.3f→%.3f task_id=%s",
            mp,
            new_mp,
            task_id,
        )

    @staticmethod
    def _read_config() -> Dict[str, Any]:
        try:
            import json
            import pathlib

            return json.loads(
                (pathlib.Path(__file__).parents[2] / "config.json").read_text()
            )
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_controller_instance: Optional[DecayController] = None
_controller_lock = threading.Lock()


def get_decay_controller() -> DecayController:
    """Return the process-wide :class:`DecayController` singleton."""
    global _controller_instance
    if _controller_instance is None:
        with _controller_lock:
            if _controller_instance is None:
                _controller_instance = DecayController()
                # Subscribe immediately so task events trigger decay automatically.
                _controller_instance.subscribe_to_task_lifecycle()
                logger.debug("DecayController singleton initialised and subscribed")
    return _controller_instance


def reset_decay_controller() -> None:
    """Reset the singleton (for testing only)."""
    global _controller_instance
    with _controller_lock:
        _controller_instance = None
