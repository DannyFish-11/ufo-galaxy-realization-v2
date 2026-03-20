"""
core.cognitive.state_interpreter — Tri-state Region Interpreter
================================================================

Maps the continuous :class:`~core.cognitive.continuous_state.CognitiveState`
into the tri-state regions used by :class:`~core.desktop_presence_runtime.TriState`
**without** hard if-else flag switches.

Design
------
The continuous state space is divided into three overlapping regions based on
``manifest_pressure``, ``activation``, and ``uncertainty``:

- **PASSIVE** (previously "silent") — low pressure, low activation.
- **LIMINAL** — moderate pressure / uncertainty; system is evaluating.
- **MANIFEST** — high pressure, low uncertainty; system is acting.

Transitions are derived from a smooth *score* function so the system can
**dwell** in the liminal region rather than jumping to manifest prematurely.
Region boundaries are configurable; the interpreter uses hysteresis to avoid
rapid oscillation (see :class:`~core.cognitive.liminal_dynamics.LiminalDynamics`).

Backward compatibility
----------------------
The returned :class:`InterpretedState` provides a ``tristate`` field that maps
to the existing :class:`~core.desktop_presence_runtime.TriState` enum values
(``"silent"`` / ``"liminal"`` / ``"manifest"``), so no existing consumer needs
to change.

Configuration (``config.json``)
--------------------------------
- ``cognitive_manifest_threshold``  (float 0–1, default ``0.65``) — pressure above
  which the interpreter enters manifest.
- ``cognitive_passive_threshold``   (float 0–1, default ``0.20``) — pressure below
  which the interpreter returns to passive.
- ``cognitive_uncertainty_cap``     (float 0–1, default ``0.70``) — uncertainty above
  this value prevents manifest even if pressure is high.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

from core.cognitive.continuous_state import CognitiveState, get_cognitive_state

logger = logging.getLogger("Galaxy.Cognitive.Interpreter")


# ---------------------------------------------------------------------------
# Region enum (mirrors TriState for compatibility)
# ---------------------------------------------------------------------------


class CognitiveRegion(str, Enum):
    """Tri-state region derived from continuous state space.

    Maps 1-to-1 with :class:`~core.desktop_presence_runtime.TriState`:
    ``PASSIVE`` ↔ ``SILENT``, ``LIMINAL`` ↔ ``LIMINAL``,
    ``MANIFEST`` ↔ ``MANIFEST``.
    """

    PASSIVE = "silent"
    LIMINAL = "liminal"
    MANIFEST = "manifest"


# ---------------------------------------------------------------------------
# Interpreted state snapshot
# ---------------------------------------------------------------------------


@dataclass
class InterpretedState:
    """Immutable snapshot from one interpreter evaluation.

    Attributes
    ----------
    region:
        Derived :class:`CognitiveRegion`.
    tristate:
        String value compatible with existing ``TriState`` consumers.
    score:
        Continuous manifest score in ``[0, 1]`` that drove the decision.
    uncertainty:
        Uncertainty value from the cognitive state at evaluation time.
    manifest_pressure:
        Manifest pressure value at evaluation time.
    activation:
        Activation value at evaluation time.
    source:
        ``"interpreter"`` — indicates tri-state was derived, not set directly.
    timestamp:
        Unix epoch of this interpretation.
    """

    region: CognitiveRegion
    tristate: str
    score: float
    uncertainty: float
    manifest_pressure: float
    activation: float
    source: str = "interpreter"
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "region": self.region.value,
            "tristate": self.tristate,
            "score": round(self.score, 4),
            "uncertainty": round(self.uncertainty, 4),
            "manifest_pressure": round(self.manifest_pressure, 4),
            "activation": round(self.activation, 4),
            "source": self.source,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Interpreter
# ---------------------------------------------------------------------------


class StateInterpreter:
    """Maps a :class:`~core.cognitive.continuous_state.CognitiveState` to a
    :class:`CognitiveRegion` using smooth threshold-based region boundaries.

    The interpreter does **not** hard-switch between states.  Instead it
    computes a continuous *manifest score* and uses hysteresis (via
    :class:`~core.cognitive.liminal_dynamics.LiminalDynamics`) to stabilise
    the liminal region.

    Parameters
    ----------
    state:
        Cognitive state to interpret.  Defaults to the process-wide singleton.
    manifest_threshold:
        Minimum manifest score to enter the manifest region.
    passive_threshold:
        Maximum manifest score to remain in the passive region.
    uncertainty_cap:
        Uncertainty above this value blocks manifest even if score is high.
    """

    def __init__(
        self,
        state: Optional[CognitiveState] = None,
        manifest_threshold: Optional[float] = None,
        passive_threshold: Optional[float] = None,
        uncertainty_cap: Optional[float] = None,
    ) -> None:
        self._state = state or get_cognitive_state()
        cfg = self._read_config()
        self._manifest_threshold = manifest_threshold or cfg.get("cognitive_manifest_threshold", 0.65)
        self._passive_threshold = passive_threshold or cfg.get("cognitive_passive_threshold", 0.20)
        self._uncertainty_cap = uncertainty_cap or cfg.get("cognitive_uncertainty_cap", 0.70)
        self._last_region = CognitiveRegion.PASSIVE
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def interpret(self, state: Optional[CognitiveState] = None) -> InterpretedState:
        """Derive the current :class:`InterpretedState` from the continuous field.

        Parameters
        ----------
        state:
            Optional override state snapshot.  Uses the engine's state when
            *None*.

        Returns
        -------
        InterpretedState:
            Immutable snapshot of the derived region and contributing values.
        """
        s = state or self._state
        snap = s.snapshot()

        mp = snap["manifest_pressure"]
        act = snap["activation"]
        unc = snap["uncertainty"]

        # Compute continuous manifest score: blend of pressure and activation,
        # dampened by uncertainty.
        raw_score = (mp * 0.6 + act * 0.4) * max(0.0, 1.0 - unc * 0.5)

        with self._lock:
            region = self._apply_hysteresis(raw_score, unc)
            self._last_region = region

        result = InterpretedState(
            region=region,
            tristate=region.value,
            score=raw_score,
            uncertainty=unc,
            manifest_pressure=mp,
            activation=act,
        )
        logger.debug(
            "StateInterpreter: score=%.3f → region=%s (pressure=%.3f act=%.3f unc=%.3f)",
            raw_score,
            region.value,
            mp,
            act,
            unc,
        )
        return result

    def interpret_snapshot(self, snapshot: Dict[str, Any]) -> InterpretedState:
        """Interpret a pre-computed state snapshot dict (no lock needed).

        Useful when the caller already holds a snapshot rather than a live
        :class:`~core.cognitive.continuous_state.CognitiveState`.
        """
        mp = float(snapshot.get("manifest_pressure", 0.0))
        act = float(snapshot.get("activation", 0.0))
        unc = float(snapshot.get("uncertainty", 0.5))

        raw_score = (mp * 0.6 + act * 0.4) * max(0.0, 1.0 - unc * 0.5)

        with self._lock:
            region = self._apply_hysteresis(raw_score, unc)
            self._last_region = region

        return InterpretedState(
            region=region,
            tristate=region.value,
            score=raw_score,
            uncertainty=unc,
            manifest_pressure=mp,
            activation=act,
        )

    @property
    def last_region(self) -> CognitiveRegion:
        """The most recently derived region (thread-safe read)."""
        with self._lock:
            return self._last_region

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_hysteresis(self, score: float, uncertainty: float) -> CognitiveRegion:
        """Apply hysteresis to prevent rapid region oscillation.

        Once in manifest, the score must drop below ``passive_threshold + 0.1``
        to leave manifest.  This prevents flicker at the threshold boundary.
        """
        current = self._last_region

        # Uncertainty cap: even high-pressure state cannot be manifest.
        if uncertainty >= self._uncertainty_cap:
            return CognitiveRegion.LIMINAL if score > self._passive_threshold else CognitiveRegion.PASSIVE

        if current == CognitiveRegion.PASSIVE:
            if score >= self._passive_threshold:
                return CognitiveRegion.LIMINAL
            return CognitiveRegion.PASSIVE

        if current == CognitiveRegion.LIMINAL:
            if score >= self._manifest_threshold:
                return CognitiveRegion.MANIFEST
            if score < self._passive_threshold:
                return CognitiveRegion.PASSIVE
            return CognitiveRegion.LIMINAL

        # current == MANIFEST
        if score < (self._passive_threshold + 0.10):
            return CognitiveRegion.PASSIVE
        if score < self._manifest_threshold:
            return CognitiveRegion.LIMINAL
        return CognitiveRegion.MANIFEST

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

_interpreter_instance: Optional[StateInterpreter] = None
_interpreter_lock = threading.Lock()


def get_state_interpreter() -> StateInterpreter:
    """Return the process-wide :class:`StateInterpreter` singleton."""
    global _interpreter_instance
    if _interpreter_instance is None:
        with _interpreter_lock:
            if _interpreter_instance is None:
                _interpreter_instance = StateInterpreter()
                logger.debug("StateInterpreter singleton initialised")
    return _interpreter_instance


def reset_state_interpreter() -> None:
    """Reset the singleton (for testing only)."""
    global _interpreter_instance
    with _interpreter_lock:
        _interpreter_instance = None
