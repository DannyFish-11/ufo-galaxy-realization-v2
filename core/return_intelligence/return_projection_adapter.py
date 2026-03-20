"""
core/return_intelligence/return_projection_adapter.py
======================================================
Adapters that connect the return engine to the projection layer.

Three public helpers are provided:

build_return_summary(result)
    Convert a :class:`~core.continuum.return_engine.ReturnResult` into a
    stable, public-facing :class:`~core.return_intelligence.ReturnSummary`.
    This is the primary bridge between the continuum engine and all downstream
    consumers.  ``None`` input produces :data:`IDLE_RETURN_SUMMARY`.

attach_return_summary(projection_dict, summary)
    Attach a :class:`ReturnSummary` to an existing
    :class:`~core.projection.RuntimeProjection` dict (or any dict with
    compatible fields) in an **additive**, backward-compatible way.  The
    return summary is nested under the key ``"return_intelligence"``.  The
    existing projection fields are never modified.

get_return_hints(summary)
    Return a plain dict of boolean downstream hints derived from the
    summary.  Useful for quick checks in Manifest Stage and Liminal
    controllers without importing the full summary object.

Design rules
------------
- These adapters are **stateless** — each call produces a fresh result.
- They do **not** modify any existing engine, projection, or routing module.
- All exceptions are caught and logged; callers always receive a valid result.
- ``receding`` is never surfaced as a public concept.

Usage::

    from core.continuum.return_engine import ReturnEngine
    from core.continuum.types import ContinuumPhase, ContinuumState
    from core.return_intelligence import (
        build_return_summary,
        attach_return_summary,
        get_return_hints,
    )

    engine = ReturnEngine()
    result = engine.evaluate(state, elapsed_ms=3000, finished=True)

    summary = build_return_summary(result)
    projection_with_return = attach_return_summary(projection_dict, summary)
    hints = get_return_hints(summary)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .return_modes import (
    ReturnMode,
    MODES_THAT_SUPPRESS_MANIFEST,
    MODES_THAT_SOFTEN_LIMINAL,
)
from .return_summary import ReturnSummary, IDLE_RETURN_SUMMARY

logger = logging.getLogger("Galaxy.ReturnIntelligence.Adapter")

# ---------------------------------------------------------------------------
# ReturnAction string → ReturnMode mapping
# ---------------------------------------------------------------------------

_ACTION_TO_MODE: Dict[str, ReturnMode] = {
    "hold": ReturnMode.HOLD,
    "soft_decay": ReturnMode.SOFT_DECAY,
    "step_down": ReturnMode.STEP_DOWN,
    "return_to_formless": ReturnMode.RETURN_TO_FORMLESS,
}


def _action_to_mode(action_value: Optional[str]) -> ReturnMode:
    """Map a :class:`~core.continuum.return_engine.ReturnAction` value to a
    :class:`ReturnMode`.

    ``None`` or unmapped strings return :attr:`ReturnMode.NONE`.
    """
    if action_value is None:
        return ReturnMode.NONE
    return _ACTION_TO_MODE.get(str(action_value), ReturnMode.NONE)


# ---------------------------------------------------------------------------
# Primary adapter: ReturnResult → ReturnSummary
# ---------------------------------------------------------------------------


def build_return_summary(result: Optional[Any]) -> ReturnSummary:
    """Build a public :class:`ReturnSummary` from a return-engine result.

    Parameters
    ----------
    result:
        A :class:`~core.continuum.return_engine.ReturnResult` instance, or
        ``None``.  When ``None``, :data:`IDLE_RETURN_SUMMARY` is returned.

    Returns
    -------
    ReturnSummary
        A stable, serialisable summary safe for public/downstream consumers.
        Never raises; falls back to :data:`IDLE_RETURN_SUMMARY` on error.

    Notes
    -----
    This function accesses ``ReturnResult`` attributes without importing the
    class directly, so it works safely even if the continuum package is
    partially unavailable.
    """
    if result is None:
        return IDLE_RETURN_SUMMARY

    try:
        # Accept both dataclass instances (ReturnResult) and dicts.
        if isinstance(result, dict):
            should_return: bool = bool(result.get("should_return", False))
            action_raw: Optional[str] = result.get("return_action")
            trigger_raw: Optional[str] = result.get("trigger")
            reason: str = str(result.get("reason") or "no reason provided")
            decay: float = float(result.get("decay_amount") or 0.0)
        else:
            should_return = bool(getattr(result, "should_return", False))
            _action = getattr(result, "return_action", None)
            action_raw = _action.value if hasattr(_action, "value") else str(_action) if _action else None
            _trigger = getattr(result, "trigger", None)
            trigger_raw = _trigger.value if hasattr(_trigger, "value") else str(_trigger) if _trigger else None
            reason = str(getattr(result, "reason", "no reason provided") or "no reason provided")
            decay = float(getattr(result, "decay_amount", 0.0) or 0.0)

        # When should_return is False the action is effectively HOLD/NONE.
        if not should_return:
            mode = ReturnMode.NONE
            action_raw = None if action_raw == "hold" else action_raw
        else:
            mode = _action_to_mode(action_raw)

        affects_manifest = mode in MODES_THAT_SUPPRESS_MANIFEST
        affects_liminal = mode in MODES_THAT_SOFTEN_LIMINAL

        return ReturnSummary(
            is_returning=should_return,
            return_mode=mode,
            return_action=action_raw,
            return_trigger=trigger_raw,
            decay_amount=max(0.0, min(1.0, decay)),
            reason=reason,
            affects_manifest=affects_manifest,
            affects_liminal=affects_liminal,
        )

    except Exception as exc:  # pragma: no cover
        logger.warning("build_return_summary: unexpected error, returning idle: %s", exc)
        return IDLE_RETURN_SUMMARY


# ---------------------------------------------------------------------------
# Additive projection attachment
# ---------------------------------------------------------------------------


def attach_return_summary(
    projection: Dict[str, Any],
    summary: ReturnSummary,
) -> Dict[str, Any]:
    """Return a **new** dict with return intelligence attached additively.

    The original ``projection`` dict is not modified.  The summary is nested
    under ``"return_intelligence"`` so that consumers can opt-in without
    breaking existing field expectations.

    Parameters
    ----------
    projection:
        A ``dict`` conforming to the ``RuntimeProjection`` schema.
    summary:
        A :class:`ReturnSummary` to attach.

    Returns
    -------
    dict
        A shallow copy of ``projection`` with ``"return_intelligence"`` added.

    Example
    -------
    ::

        enriched = attach_return_summary(projection.to_dict(), summary)
        # enriched["return_intelligence"]["is_returning"] → bool
        # enriched["tri_state_phase"] → unchanged
    """
    enriched = dict(projection)
    enriched["return_intelligence"] = summary.to_dict()
    return enriched


# ---------------------------------------------------------------------------
# Downstream hint helper
# ---------------------------------------------------------------------------


def get_return_hints(summary: ReturnSummary) -> Dict[str, Any]:
    """Derive a compact dict of boolean/scalar hints from a :class:`ReturnSummary`.

    Designed for use by Manifest Stage controllers, Liminal engines, and
    Status Board surfaces that only need quick boolean checks without importing
    the full summary class.

    Parameters
    ----------
    summary:
        A :class:`ReturnSummary` (or :data:`IDLE_RETURN_SUMMARY` for defaults).

    Returns
    -------
    dict with keys:
        - ``is_returning``       (bool)
        - ``suppresses_manifest``(bool)
        - ``softens_liminal``    (bool)
        - ``decay_amount``       (float)
        - ``return_mode``        (str)
    """
    return {
        "is_returning": summary.is_returning,
        "suppresses_manifest": summary.affects_manifest,
        "softens_liminal": summary.affects_liminal,
        "decay_amount": summary.decay_amount,
        "return_mode": summary.return_mode.value,
    }
