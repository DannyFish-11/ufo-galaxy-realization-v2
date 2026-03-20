"""
core.cognitive.liminal_dynamics — Liminal Region Stabilisation
==============================================================

Provides :class:`LiminalDynamics`: a component that stabilises the liminal
region in the cognitive field, preventing premature manifest transitions and
enabling the system to **dwell** in the liminal state when appropriate.

Design
------
The liminal region is the key transitional zone.  Without stabilisation the
system would oscillate rapidly between passive and manifest whenever the
continuous score hovers near a threshold.  ``LiminalDynamics`` implements:

1. **Entry guard** — a minimum dwell time (in seconds) before a liminal→manifest
   transition is allowed.  This gives the system time to evaluate intent.
2. **Exit guard** — manifest→liminal transitions are smooth: the field is not
   reset but instead allowed to decay naturally (handled by
   :class:`~core.cognitive.decay_controller.DecayController`).
3. **Oscillation damping** — rapid transitions increment a *volatility counter*;
   high volatility temporarily raises the manifest threshold.

Configuration (``config.json``)
--------------------------------
- ``cognitive_liminal_min_dwell_s`` (float, default ``1.5``) — minimum seconds in
  liminal before manifest transition is permitted.
- ``cognitive_liminal_volatility_window`` (int, default ``5``) — number of recent
  transitions used to compute volatility.
- ``cognitive_liminal_volatility_penalty`` (float, default ``0.10``) — manifest
  threshold is raised by this amount per unit of excess volatility.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, Optional, Tuple

logger = logging.getLogger("Galaxy.Cognitive.Liminal")


class LiminalDynamics:
    """Stabilises the liminal region to prevent oscillation and premature transitions.

    Parameters
    ----------
    min_dwell_s:
        Minimum seconds the cognitive field must dwell in the liminal region
        before a manifest transition is allowed.
    volatility_window:
        Number of recent region transitions used to compute volatility.
    volatility_penalty:
        Manifest threshold increment per unit of excess volatility (>1 per window).
    """

    def __init__(
        self,
        min_dwell_s: Optional[float] = None,
        volatility_window: Optional[int] = None,
        volatility_penalty: Optional[float] = None,
    ) -> None:
        cfg = self._read_config()
        self._min_dwell_s = min_dwell_s if min_dwell_s is not None else float(
            cfg.get("cognitive_liminal_min_dwell_s", 1.5)
        )
        self._volatility_window = volatility_window or int(
            cfg.get("cognitive_liminal_volatility_window", 5)
        )
        self._volatility_penalty = volatility_penalty if volatility_penalty is not None else float(
            cfg.get("cognitive_liminal_volatility_penalty", 0.10)
        )

        self._liminal_entered_at: Optional[float] = None
        # Deque of (from_region, to_region, timestamp) transition records
        self._transition_history: Deque[Tuple[str, str, float]] = deque(
            maxlen=self._volatility_window * 2
        )
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_transition(self, from_region: str, to_region: str) -> None:
        """Record a region transition for volatility tracking.

        Must be called **after** every region change so that dwell times
        and volatility are computed correctly.

        Parameters
        ----------
        from_region:
            The region that was left (e.g. ``"liminal"``).
        to_region:
            The region entered (e.g. ``"manifest"``).
        """
        now = time.time()
        with self._lock:
            self._transition_history.append((from_region, to_region, now))
            if to_region == "liminal":
                self._liminal_entered_at = now
            elif from_region == "liminal":
                self._liminal_entered_at = None

        logger.debug(
            "LiminalDynamics: transition %s → %s | volatility=%.2f",
            from_region,
            to_region,
            self.volatility(),
        )

    def can_transition_to_manifest(self) -> bool:
        """Return *True* if the system has dwelt long enough in liminal.

        Also returns *True* immediately when the system is **not** currently
        in the liminal region (dwell check only applies from liminal).
        """
        with self._lock:
            if self._liminal_entered_at is None:
                # Not in liminal — transition gating does not apply.
                return True
            dwell = time.time() - self._liminal_entered_at
            allowed = dwell >= self._min_dwell_s
            if not allowed:
                logger.debug(
                    "LiminalDynamics: manifest blocked — dwell=%.2fs < min=%.2fs",
                    dwell,
                    self._min_dwell_s,
                )
            return allowed

    def volatility(self) -> float:
        """Compute normalised volatility from recent transition history.

        Returns a value in ``[0, 1]`` where ``0`` is completely stable and
        ``1`` indicates maximum oscillation within the window.

        Volatility is measured as the fraction of direction reversals in the
        transition sequence.  A "direction reversal" occurs when consecutive
        transitions change from moving toward manifest to moving toward passive
        or vice versa.
        """
        _toward_manifest = {("silent", "liminal"), ("liminal", "manifest")}
        _toward_passive = {("manifest", "liminal"), ("liminal", "silent"), ("manifest", "silent")}

        def _direction(from_r: str, to_r: str) -> int:
            key = (from_r, to_r)
            if key in _toward_manifest:
                return 1
            if key in _toward_passive:
                return -1
            return 0

        with self._lock:
            if not self._transition_history:
                return 0.0
            recent = list(self._transition_history)[-self._volatility_window:]

        if len(recent) < 2:
            return 0.0

        directions = [_direction(t[0], t[1]) for t in recent]
        non_zero = [d for d in directions if d != 0]
        if len(non_zero) < 2:
            return 0.0

        reversals = sum(
            1
            for i in range(1, len(non_zero))
            if non_zero[i] != non_zero[i - 1]
        )
        return min(1.0, reversals / max(1, len(non_zero) - 1))

    def manifest_threshold_adjustment(self) -> float:
        """Return an upward threshold adjustment based on current volatility.

        When the field is oscillating frequently the effective manifest
        threshold is raised to prevent flip-flopping.
        """
        vol = self.volatility()
        # Only penalise when volatility > 0.3 (allow some natural movement)
        excess = max(0.0, vol - 0.3)
        return excess * self._volatility_penalty

    def liminal_dwell_s(self) -> float:
        """Return seconds spent in the current liminal phase (0 if not liminal)."""
        with self._lock:
            if self._liminal_entered_at is None:
                return 0.0
            return time.time() - self._liminal_entered_at

    def state_dict(self) -> Dict[str, Any]:
        """Return an observable state snapshot."""
        return {
            "liminal_dwell_s": round(self.liminal_dwell_s(), 3),
            "volatility": round(self.volatility(), 4),
            "threshold_adjustment": round(self.manifest_threshold_adjustment(), 4),
            "min_dwell_s": self._min_dwell_s,
            "transition_count": len(self._transition_history),
        }

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

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

_dynamics_instance: Optional[LiminalDynamics] = None
_dynamics_lock = threading.Lock()


def get_liminal_dynamics() -> LiminalDynamics:
    """Return the process-wide :class:`LiminalDynamics` singleton."""
    global _dynamics_instance
    if _dynamics_instance is None:
        with _dynamics_lock:
            if _dynamics_instance is None:
                _dynamics_instance = LiminalDynamics()
                logger.debug("LiminalDynamics singleton initialised")
    return _dynamics_instance


def reset_liminal_dynamics() -> None:
    """Reset the singleton (for testing only)."""
    global _dynamics_instance
    with _dynamics_lock:
        _dynamics_instance = None
