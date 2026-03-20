"""
desktop_projection/state_space_mapper.py
==========================================
Maps a :class:`~core.projection.RuntimeProjection` into a
:class:`LiminalSpaceState` — a thin, spatial-dimension description that the
:class:`~desktop_projection.LiminalSpaceEngine` and
:class:`~desktop_projection.TransitionAnimator` use to drive the desktop
transition sequence.

Design
------
The mapper is **pure** (no side effects, no I/O).  It reads fields from a
``RuntimeProjection`` dict or object and produces a fully-populated
``LiminalSpaceState`` with values in ``[0, 1]`` for every dimension.

Dimension → source mapping
--------------------------
depth_factor
    Derived from ``tri_state_phase`` (base anchor) and ``collapse_tendency``
    (pushes depth toward manifest).  Silent → shallow, Manifest → deep.
topology_visibility
    Derived from the L∞ (max) magnitude of ``active_weights``.  No weights →
    topology invisible; strong, uniform weights → fully visible.
domain_path_emphasis
    Derived from ``runtime_domain``.  Local → no path emphasis; transition →
    partial; cross_device → full path display.
ambient_intensity
    Derived from ``presence_intensity`` and ``coherence`` (geometric mean).
    Represents how "alive" the ambient field feels.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Optional, Union

# We import these lazily-compatible: the mapper accepts plain dicts OR typed
# objects, so that callers who only have a dict (e.g. from an HTTP endpoint)
# do not need to import the full core stack.
try:
    from core.continuum.types import RuntimeDomain, TriStatePhase
    _HAS_TYPES = True
except ImportError:  # pragma: no cover
    _HAS_TYPES = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Base depth values per tri-state phase (before collapse-tendency adjustment).
_DEPTH_BASE: Dict[str, float] = {
    "silent": 0.05,
    "liminal": 0.50,
    "manifest": 0.95,
}

# Domain path emphasis anchors.
_DOMAIN_EMPHASIS: Dict[str, float] = {
    "local": 0.0,
    "transition": 0.5,
    "cross_device": 1.0,
}


# ---------------------------------------------------------------------------
# LiminalSpaceState
# ---------------------------------------------------------------------------


@dataclass
class LiminalSpaceState:
    """A thin spatial-dimension descriptor derived from a RuntimeProjection.

    All dimension values are normalised to ``[0.0, 1.0]``.  Consumers should
    interpret them as continuous intensities, not binary flags.

    Attributes
    ----------
    depth_factor
        How "deep" the spatial projection currently is.  0 = fully collapsed
        to surface (silent), 1 = fully extended (manifest).
    topology_visibility
        How visible the model-topology layer is.  0 = hidden, 1 = fully shown.
    domain_path_emphasis
        How prominently the runtime-domain path is displayed.  0 = local
        (no path), 1 = cross-device (full path display).
    ambient_intensity
        Derived ambient-field strength (geometric mean of presence_intensity
        and coherence).  0 = dark/quiet, 1 = bright/active.
    source_phase
        The tri_state_phase string from the original projection.
    source_domain
        The runtime_domain string (or None) from the original projection.
    """

    depth_factor: float = 0.0
    topology_visibility: float = 0.0
    domain_path_emphasis: float = 0.0
    ambient_intensity: float = 0.0
    source_phase: str = "silent"
    source_domain: Optional[str] = None

    def to_dict(self) -> dict:
        """Return a plain dict representation."""
        return {
            "depth_factor": self.depth_factor,
            "topology_visibility": self.topology_visibility,
            "domain_path_emphasis": self.domain_path_emphasis,
            "ambient_intensity": self.ambient_intensity,
            "source_phase": self.source_phase,
            "source_domain": self.source_domain,
        }

    def __repr__(self) -> str:
        return (
            f"<LiminalSpaceState "
            f"phase={self.source_phase} "
            f"depth={self.depth_factor:.3f} "
            f"topo={self.topology_visibility:.3f} "
            f"path={self.domain_path_emphasis:.3f} "
            f"ambient={self.ambient_intensity:.3f}>"
        )


# ---------------------------------------------------------------------------
# StateSpaceMapper
# ---------------------------------------------------------------------------


class StateSpaceMapper:
    """Stateless mapper: RuntimeProjection → LiminalSpaceState.

    The mapper accepts either a plain ``dict`` (e.g. from an HTTP JSON
    response) or a typed ``RuntimeProjection`` object.  This keeps the
    desktop_projection package loosely coupled to the core stack.

    Usage::

        mapper = StateSpaceMapper()
        state = mapper.map(projection_dict)
    """

    # Weight given to collapse_tendency when nudging depth beyond the phase base.
    _COLLAPSE_DEPTH_WEIGHT: float = 0.25

    def map(
        self,
        projection: Union[dict, object],
    ) -> LiminalSpaceState:
        """Map *projection* to a :class:`LiminalSpaceState`.

        Parameters
        ----------
        projection:
            A ``dict`` conforming to the ``RuntimeProjection`` schema, or
            an actual ``RuntimeProjection`` instance.

        Returns
        -------
        LiminalSpaceState
            Fully-populated spatial descriptor.
        """
        p = _to_dict(projection)

        phase_str: str = _safe_str(p.get("tri_state_phase"), "silent")
        domain_str: Optional[str] = _safe_str(p.get("runtime_domain"), None)
        presence: float = _safe_float(p.get("presence_intensity"), 0.0)
        coherence: float = _safe_float(p.get("coherence"), 0.0)
        collapse: float = _safe_float(p.get("collapse_tendency"), 0.0)
        active_weights: Dict[str, float] = dict(p.get("active_weights") or {})

        depth = self._compute_depth(phase_str, collapse)
        topo = self._compute_topology_visibility(active_weights)
        path = self._compute_domain_path(domain_str)
        ambient = self._compute_ambient(presence, coherence)

        return LiminalSpaceState(
            depth_factor=depth,
            topology_visibility=topo,
            domain_path_emphasis=path,
            ambient_intensity=ambient,
            source_phase=phase_str,
            source_domain=domain_str,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_depth(self, phase: str, collapse: float) -> float:
        """depth = phase_base + collapse_weight * collapse_tendency (clamped)."""
        base = _DEPTH_BASE.get(phase, 0.05)
        nudge = self._COLLAPSE_DEPTH_WEIGHT * collapse
        return _clamp(base + nudge, 0.0, 1.0)

    def _compute_topology_visibility(self, weights: Dict[str, float]) -> float:
        """topology_visibility = max weight magnitude, clamped to [0, 1]."""
        if not weights:
            return 0.0
        return _clamp(max(abs(w) for w in weights.values()), 0.0, 1.0)

    def _compute_domain_path(self, domain: Optional[str]) -> float:
        """domain_path_emphasis from the domain string."""
        if domain is None:
            return 0.0
        return _DOMAIN_EMPHASIS.get(domain, 0.0)

    def _compute_ambient(self, presence: float, coherence: float) -> float:
        """ambient_intensity = geometric mean of presence and coherence."""
        product = max(presence, 0.0) * max(coherence, 0.0)
        return _clamp(math.sqrt(product), 0.0, 1.0)


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------


def _to_dict(projection: Union[dict, object]) -> dict:
    """Coerce a RuntimeProjection (or compatible object) to a plain dict."""
    if isinstance(projection, dict):
        return projection
    # Support .to_dict() as defined on RuntimeProjection.
    if hasattr(projection, "to_dict"):
        return projection.to_dict()  # type: ignore[union-attr]
    # Fallback: try __dict__.
    return vars(projection)


def _safe_float(value: object, default: float) -> float:
    """Return *value* as float, or *default* if None / non-numeric."""
    if value is None:
        return default
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _safe_str(value: object, default: Optional[str]) -> Optional[str]:
    """Return *value* as str, or *default* if None."""
    if value is None:
        return default
    # Handle enum members (e.g. TriStatePhase).
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp *value* to [*lo*, *hi*]."""
    return max(lo, min(hi, value))
