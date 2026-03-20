"""
core.cognitive.continuous_state — Continuous Cognitive State Variables
======================================================================

Defines the :class:`CognitiveState` dataclass which holds the continuous
cognitive field variables for the Galaxy system.

Variables
---------
- ``activation``        — Overall system arousal / readiness [0, 1].
- ``intent_strength``   — Strength of forming intent signal [0, 1].
- ``uncertainty``       — Epistemic uncertainty about current context [0, 1].
- ``momentum``          — Cognitive inertia carrying previous state forward [0, 1].
- ``manifest_pressure`` — Accumulated pressure toward manifest action [0, 1].
- ``stability``         — Temporal stability of the field (low = oscillating) [0, 1].
- ``decay_rate``        — Current rate of decay per tick (configurable) [0, 1].
- ``timestamp``         — Unix epoch seconds of last update.

All float fields are clamped to ``[0.0, 1.0]`` on assignment via
:meth:`CognitiveState.update`.

Thread-safety: :meth:`update` and :meth:`snapshot` are protected by a
:class:`threading.Lock`; safe for concurrent read/write from asyncio + threads.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.Cognitive.State")


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Return *v* clamped to [*lo*, *hi*]."""
    return max(lo, min(hi, float(v)))


@dataclass
class CognitiveState:
    """Continuous cognitive field variable snapshot.

    This object is mutable and is updated in-place by the
    :class:`~core.cognitive.cognitive_field_engine.CognitiveFieldEngine`.
    Call :meth:`snapshot` to obtain an immutable copy.

    Parameters
    ----------
    activation:
        Overall system arousal / readiness.  Low values represent a
        quiet background state; high values indicate heightened attention.
    intent_strength:
        Strength of the intent currently forming.  Drives
        ``manifest_pressure`` when sustained.
    uncertainty:
        Epistemic uncertainty.  High uncertainty reduces ``manifest_pressure``
        and stabilises the liminal region.
    momentum:
        Cognitive inertia.  Causes the field to persist in its current
        direction rather than snapping to new inputs instantly.
    manifest_pressure:
        Accumulated pressure toward manifest action.  When this crosses
        the interpreter threshold the field enters the manifest region.
    stability:
        Temporal stability of the field.  Low values indicate recent
        oscillation or rapid phase changes.
    decay_rate:
        Per-tick decay amount applied to ``manifest_pressure`` and
        ``activation`` when in the post-manifest reabsorption phase.
    timestamp:
        Unix epoch seconds of the last :meth:`update` call.
    """

    activation: float = 0.0
    intent_strength: float = 0.0
    uncertainty: float = 0.5
    momentum: float = 0.0
    manifest_pressure: float = 0.0
    stability: float = 1.0
    decay_rate: float = 0.05
    timestamp: float = field(default_factory=time.time)

    # Internal lock — not included in asdict() output.
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def update(self, **kwargs: float) -> None:
        """Update one or more fields, clamping all float values to [0, 1].

        ``timestamp`` is automatically refreshed.  ``decay_rate`` is clamped
        to ``[0.0, 1.0]`` like all other fields.

        Parameters
        ----------
        **kwargs:
            Any subset of the float fields of :class:`CognitiveState`.

        Raises
        ------
        ValueError:
            If an unknown field name is passed.
        """
        _float_fields = {
            "activation",
            "intent_strength",
            "uncertainty",
            "momentum",
            "manifest_pressure",
            "stability",
            "decay_rate",
        }
        unknown = set(kwargs) - _float_fields - {"timestamp"}
        if unknown:
            raise ValueError(f"CognitiveState.update: unknown fields {unknown!r}")

        with self._lock:
            for k, v in kwargs.items():
                if k == "timestamp":
                    object.__setattr__(self, k, float(v))
                else:
                    object.__setattr__(self, k, _clamp(v))
            object.__setattr__(self, "timestamp", time.time())

    def snapshot(self) -> Dict[str, Any]:
        """Return a plain-dict snapshot (no lock held by caller required).

        The dict is safe to serialise to JSON.  The internal ``_lock`` field
        is excluded.
        """
        with self._lock:
            return {
                "activation": self.activation,
                "intent_strength": self.intent_strength,
                "uncertainty": self.uncertainty,
                "momentum": self.momentum,
                "manifest_pressure": self.manifest_pressure,
                "stability": self.stability,
                "decay_rate": self.decay_rate,
                "timestamp": self.timestamp,
            }

    def apply_input(
        self,
        *,
        intent_delta: float = 0.0,
        activation_delta: float = 0.0,
        uncertainty_override: Optional[float] = None,
    ) -> None:
        """Apply an external input signal to the state.

        This is the primary method for injecting signals from new requests.
        Deltas are blended with momentum to produce smooth changes.

        Parameters
        ----------
        intent_delta:
            Change in intent strength (positive = more intent).
        activation_delta:
            Change in activation (positive = more aroused).
        uncertainty_override:
            If provided, overrides the current uncertainty directly.
        """
        with self._lock:
            # Blend with momentum: new = old * momentum + delta * (1 - momentum)
            m = self.momentum
            new_intent = _clamp(self.intent_strength * m + (self.intent_strength + intent_delta) * (1.0 - m))
            new_activation = _clamp(self.activation * m + (self.activation + activation_delta) * (1.0 - m))
            new_uncertainty = _clamp(uncertainty_override) if uncertainty_override is not None else self.uncertainty

            # Manifest pressure builds from intent × activation
            new_mp = _clamp(self.manifest_pressure + new_intent * new_activation * 0.1)

            object.__setattr__(self, "intent_strength", new_intent)
            object.__setattr__(self, "activation", new_activation)
            object.__setattr__(self, "uncertainty", new_uncertainty)
            object.__setattr__(self, "manifest_pressure", new_mp)
            object.__setattr__(self, "timestamp", time.time())

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"CognitiveState(activation={self.activation:.3f}, "
            f"intent={self.intent_strength:.3f}, "
            f"uncertainty={self.uncertainty:.3f}, "
            f"momentum={self.momentum:.3f}, "
            f"manifest_pressure={self.manifest_pressure:.3f}, "
            f"stability={self.stability:.3f})"
        )


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_state_instance: Optional[CognitiveState] = None
_state_lock = threading.Lock()


def get_cognitive_state() -> CognitiveState:
    """Return the process-wide :class:`CognitiveState` singleton.

    Thread-safe construction on first call.
    """
    global _state_instance
    if _state_instance is None:
        with _state_lock:
            if _state_instance is None:
                _state_instance = CognitiveState()
                logger.debug("CognitiveState singleton initialised")
    return _state_instance


def reset_cognitive_state() -> None:
    """Reset the singleton (for testing only)."""
    global _state_instance
    with _state_lock:
        _state_instance = None
