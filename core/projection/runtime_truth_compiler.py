"""
core/projection/runtime_truth_compiler.py
==========================================
Canonical runtime truth compiler — the single compilation point for
runtime-facing output state.

**Architecture role**
---------------------
This module is the **sole authority** for assembling a ``RuntimeTruthSnapshot``:
the one place in the runtime where all runtime state sources are gathered,
normalised, and expressed as a single stable output object.

Routes, desktop consumers, dashboard adapters, and any other output-facing
layer must source runtime truth from this module rather than re-deriving state
independently from multiple subsystems.

Authority declaration::

    RUNTIME_TRUTH_COMPILER_AUTHORITY = (
        "core.projection.runtime_truth_compiler.compile_runtime_truth"
    )

If you find yourself assembling runtime status by importing directly from
``core.multi_llm_router``, ``core.system_resource``, ``core.oneapi_system_position``,
or ``core.desktop_presence_runtime`` inside a route handler, you should instead
call :func:`compile_runtime_truth` and read from the resulting snapshot.

**Sources of truth (in dependency order)**
-------------------------------------------
1. **ContinuumState** — tri-state lifecycle phase, runtime domain, coherence,
   presence intensity, collapse/retreat tendencies.  Sourced from the cognitive
   field engine or a canonical silent fallback.
2. **TopologyRoutePlan** — canonical model/provider routing.  Sourced from the
   ``TopologyRouter`` when a route plan has been established.
3. **OneAPIStatusSummary** — OneAPI aggregator integration snapshot.  Always a
   lower-horizon block; never a top-tier provider peer.  Sourced from
   :mod:`core.oneapi_system_position`.
4. **SystemResourceSnapshot** — lightweight system resource health summary.
   Sourced from :class:`~core.system_resource.SystemResourceRegistry`.
5. **DevicePresenceSnapshot** — count and online/registered device summary.
   Sourced from :mod:`core.routes._shared` shared state.

**Compiled outputs**
--------------------
:class:`RuntimeTruthSnapshot` exposes:

- :attr:`~RuntimeTruthSnapshot.continuum` — continuum state dict (or ``None``)
- :attr:`~RuntimeTruthSnapshot.topology` — route-plan summary dict (or ``None``)
- :attr:`~RuntimeTruthSnapshot.oneapi` — OneAPI lower-horizon dict
- :attr:`~RuntimeTruthSnapshot.system_resource` — resource health dict
- :attr:`~RuntimeTruthSnapshot.device_presence` — device counts dict
- :attr:`~RuntimeTruthSnapshot.compiled_at` — Unix epoch float
- :attr:`~RuntimeTruthSnapshot.compiler_authority` — always equals
  :data:`RUNTIME_TRUTH_COMPILER_AUTHORITY`

Usage::

    from core.projection.runtime_truth_compiler import (
        compile_runtime_truth,
        RuntimeTruthSnapshot,
        RUNTIME_TRUTH_COMPILER_AUTHORITY,
    )

    snapshot = compile_runtime_truth()
    # Use snapshot in a route handler — no direct subsystem imports needed
    print(snapshot.continuum)         # dict or None
    print(snapshot.topology)          # dict or None
    print(snapshot.oneapi)            # dict — always has system_layer key
    print(snapshot.device_presence)   # {"registered": int, "online": int}
    print(snapshot.compiler_authority)  # == RUNTIME_TRUTH_COMPILER_AUTHORITY

**Endpoint guidance**
---------------------
``GET /api/v1/projection/runtime-truth`` (added in ``core/routes/projection.py``)
exposes the snapshot from :func:`compile_runtime_truth` as the single
canonical read-only endpoint for runtime truth.  All other status/observability
endpoints that expose overlapping runtime state are **compatibility endpoints**
and should adapt from this snapshot rather than re-deriving state.

See ``docs/PROJECTION_OUTPUT_AUTHORITY.md`` for the full canonical output
authority model.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

_logger = logging.getLogger("Galaxy.Projection.RuntimeTruthCompiler")

__all__ = [
    "RUNTIME_TRUTH_COMPILER_AUTHORITY",
    "RuntimeTruthSnapshot",
    "compile_runtime_truth",
]

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

#: Sentinel string identifying :func:`compile_runtime_truth` as the single
#: canonical assembly function for runtime truth snapshots.
#:
#: Downstream consumers (routes, desktop adapters, dashboards) can verify
#: the provenance of a snapshot by checking::
#:
#:     assert snapshot.compiler_authority == RUNTIME_TRUTH_COMPILER_AUTHORITY
#:
#: Any code path that assembles runtime status by importing directly from
#: subsystem modules (multi_llm_router, system_resource, oneapi_system_position,
#: etc.) is operating *outside* the canonical projection path.
RUNTIME_TRUTH_COMPILER_AUTHORITY: str = (
    "core.projection.runtime_truth_compiler.compile_runtime_truth"
)


# ---------------------------------------------------------------------------
# RuntimeTruthSnapshot
# ---------------------------------------------------------------------------


class RuntimeTruthSnapshot:
    """Immutable snapshot of compiled runtime truth.

    Produced exclusively by :func:`compile_runtime_truth`.  All fields are
    read-only after construction.

    Attributes
    ----------
    continuum:
        Dict snapshot of the current :class:`~core.continuum.types.ContinuumState`,
        or ``None`` when the continuum layer is unavailable.  Contains at
        minimum ``tri_state_phase`` and ``runtime_domain`` when present.
    topology:
        Dict snapshot of the current
        :class:`~core.model_topology.topology_router.TopologyRoutePlan`, or
        ``None`` when no route plan has been established.  Contains at minimum
        ``primary_model`` and ``primary_provider`` when present.
    oneapi:
        Dict snapshot of the OneAPI aggregator integration layer.  Always
        present (never ``None``); always carries
        ``system_layer == "aggregator_integration"`` to enforce OneAPI's
        lower-horizon position.  See :mod:`core.oneapi_system_position`.
    system_resource:
        Dict snapshot of the system resource registry health summary, or
        ``None`` when the resource registry is unavailable.
    device_presence:
        Dict with ``registered`` (int) and ``online`` (int) device counts.
        Always present; defaults to zeros when device state is unavailable.
    compiled_at:
        Unix epoch float at which this snapshot was compiled.
    compiler_authority:
        Always equal to :data:`RUNTIME_TRUTH_COMPILER_AUTHORITY`.  Confirms
        canonical provenance.
    """

    __slots__ = (
        "continuum",
        "topology",
        "oneapi",
        "system_resource",
        "device_presence",
        "compiled_at",
        "compiler_authority",
    )

    def __init__(
        self,
        *,
        continuum: Optional[Dict[str, Any]],
        topology: Optional[Dict[str, Any]],
        oneapi: Dict[str, Any],
        system_resource: Optional[Dict[str, Any]],
        device_presence: Dict[str, Any],
        compiled_at: float,
    ) -> None:
        self.continuum = continuum
        self.topology = topology
        self.oneapi = oneapi
        self.system_resource = system_resource
        self.device_presence = device_presence
        self.compiled_at = compiled_at
        self.compiler_authority: str = RUNTIME_TRUTH_COMPILER_AUTHORITY

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def has_canonical_topology(self) -> bool:
        """``True`` when topology routing is available and authoritative."""
        return (
            self.topology is not None
            and self.topology.get("routing_authority_source") == "topology_router"
        )

    @property
    def tri_state_phase(self) -> Optional[str]:
        """The current tri-state lifecycle phase, or ``None``."""
        if self.continuum is None:
            return None
        return self.continuum.get("tri_state_phase")

    @property
    def primary_model_id(self) -> Optional[str]:
        """The canonical primary model ID from the route plan, or ``None``."""
        if self.topology is None:
            return None
        return self.topology.get("primary_model")

    @property
    def primary_provider_id(self) -> Optional[str]:
        """The canonical primary provider ID from the route plan, or ``None``."""
        if self.topology is None:
            return None
        return self.topology.get("primary_provider")

    @property
    def oneapi_is_lower_horizon_only(self) -> bool:
        """Always ``True`` — OneAPI is always a lower-horizon integration block."""
        return self.oneapi.get("system_layer") == "aggregator_integration"

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of the snapshot."""
        return {
            "compiled_at": self.compiled_at,
            "compiler_authority": self.compiler_authority,
            "continuum": self.continuum,
            "topology": self.topology,
            "oneapi": self.oneapi,
            "system_resource": self.system_resource,
            "device_presence": self.device_presence,
            # Derived convenience flags
            "has_canonical_topology": self.has_canonical_topology,
            "tri_state_phase": self.tri_state_phase,
            "primary_model_id": self.primary_model_id,
            "primary_provider_id": self.primary_provider_id,
            "oneapi_is_lower_horizon_only": self.oneapi_is_lower_horizon_only,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"RuntimeTruthSnapshot("
            f"tri_state_phase={self.tri_state_phase!r}, "
            f"primary_model_id={self.primary_model_id!r}, "
            f"compiled_at={self.compiled_at!r})"
        )


# ---------------------------------------------------------------------------
# compile_runtime_truth
# ---------------------------------------------------------------------------


def compile_runtime_truth() -> RuntimeTruthSnapshot:
    """Compile a :class:`RuntimeTruthSnapshot` from all canonical sources.

    This is the **single entry-point** for assembling runtime-facing output
    state.  It gathers state from each canonical subsystem once, normalises
    it, and returns an immutable snapshot.

    No external state is modified.  All subsystem imports are attempted with
    graceful fallback to ``None`` / safe defaults so this function never raises
    in production.

    Returns
    -------
    RuntimeTruthSnapshot
        Snapshot with :attr:`~RuntimeTruthSnapshot.compiler_authority` equal
        to :data:`RUNTIME_TRUTH_COMPILER_AUTHORITY`.
    """
    compiled_at = time.time()

    continuum = _compile_continuum()
    topology = _compile_topology(continuum)
    oneapi = _compile_oneapi()
    system_resource = _compile_system_resource()
    device_presence = _compile_device_presence()

    return RuntimeTruthSnapshot(
        continuum=continuum,
        topology=topology,
        oneapi=oneapi,
        system_resource=system_resource,
        device_presence=device_presence,
        compiled_at=compiled_at,
    )


# ---------------------------------------------------------------------------
# Source compilers — one per truth source
# ---------------------------------------------------------------------------


def _compile_continuum() -> Optional[Dict[str, Any]]:
    """Source #1: ContinuumState."""
    # Try cognitive field engine (Block-3 integration)
    try:
        from core.cognitive.cognitive_field_engine import CognitiveFieldEngine

        engine = CognitiveFieldEngine.get_instance()
        if engine is not None and hasattr(engine, "get_continuum_state"):
            state = engine.get_continuum_state()
            if state is not None:
                return _safe_continuum_dict(state)
    except Exception:
        pass

    # Fallback: DesktopPresenceRuntime
    try:
        from core.desktop_presence_runtime import DesktopPresenceRuntime

        dpr = DesktopPresenceRuntime._instance if hasattr(DesktopPresenceRuntime, "_instance") else None
        if dpr is not None and hasattr(dpr, "_continuum_state"):
            state = dpr._continuum_state
            if state is not None:
                return _safe_continuum_dict(state)
    except Exception:
        pass

    # Fallback: minimal silent state
    try:
        from core.continuum.types import ContinuumPhase, ContinuumState, RuntimeDomain

        state = ContinuumState(
            phase=ContinuumPhase.SILENT,
            runtime_domain=RuntimeDomain.LOCAL,
        )
        return _safe_continuum_dict(state)
    except Exception as exc:
        _logger.debug("_compile_continuum: fallback state unavailable: %s", exc)
        return None


def _safe_continuum_dict(state: Any) -> Dict[str, Any]:
    """Extract a safe dict from a ContinuumState-like object."""
    try:
        if hasattr(state, "to_dict"):
            raw = state.to_dict()
            # Return only projection-relevant keys
            return {
                "tri_state_phase": raw.get("tri_state_phase") or raw.get("phase"),
                "runtime_domain": raw.get("runtime_domain") or raw.get("domain"),
                "coherence": raw.get("coherence"),
                "presence_intensity": raw.get("presence_intensity"),
                "collapse_tendency": raw.get("collapse_tendency"),
                "retreat_tendency": raw.get("retreat_tendency"),
            }
    except Exception:
        pass
    try:
        phase_val = getattr(state, "phase", None) or getattr(state, "tri_state_phase", None)
        domain_val = getattr(state, "runtime_domain", None) or getattr(state, "domain", None)
        return {
            "tri_state_phase": phase_val.value if hasattr(phase_val, "value") else str(phase_val) if phase_val else None,
            "runtime_domain": domain_val.value if hasattr(domain_val, "value") else str(domain_val) if domain_val else None,
            "coherence": getattr(state, "coherence", None),
            "presence_intensity": getattr(state, "presence_intensity", None),
            "collapse_tendency": getattr(state, "collapse_tendency", None),
            "retreat_tendency": getattr(state, "retreat_tendency", None),
        }
    except Exception:
        return {}


def _compile_topology(continuum: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Source #2: TopologyRoutePlan.

    Only attempted when a continuum snapshot is available (a route plan
    requires a phase/domain to route against).
    """
    try:
        from core.model_topology import TopologyRouter, ProviderInventory
        from core.model_topology.topology_router import CANONICAL_ROUTING_AUTHORITY

        inventory = ProviderInventory.from_env()
        router = TopologyRouter(inventory)

        phase_val = None
        domain_val = None
        if continuum:
            phase_val = continuum.get("tri_state_phase")
            domain_val = continuum.get("runtime_domain")

        try:
            from core.continuum.types import ContinuumPhase, RuntimeDomain

            phase = ContinuumPhase(phase_val) if phase_val else ContinuumPhase.SILENT
            domain = RuntimeDomain(domain_val) if domain_val else RuntimeDomain.LOCAL
        except Exception:
            from core.continuum.types import ContinuumPhase, RuntimeDomain

            phase = ContinuumPhase.SILENT
            domain = RuntimeDomain.LOCAL

        plan = router.route(phase, domain)
        if plan is None:
            return None

        plan_dict = plan.to_dict() if hasattr(plan, "to_dict") else {}
        return {
            "primary_model": plan_dict.get("primary_model"),
            "primary_provider": plan_dict.get("primary_provider"),
            "support_models": plan_dict.get("support_models", []),
            "route_reason": plan_dict.get("route_reason"),
            "routing_authority_source": "topology_router",
            "routing_authority": CANONICAL_ROUTING_AUTHORITY,
            "is_native_multimodal": plan_dict.get("is_native_multimodal", False),
            "active_weights": plan_dict.get("active_weights", {}),
        }
    except Exception as exc:
        _logger.debug("_compile_topology: unavailable: %s", exc)
        return None


def _compile_oneapi() -> Dict[str, Any]:
    """Source #3: OneAPI aggregator integration status.

    Always returns a dict with ``system_layer == "aggregator_integration"``
    to enforce OneAPI's canonical lower-horizon position.  See
    :mod:`core.oneapi_system_position`.
    """
    try:
        from core.oneapi_system_position import (
            ONEAPI_SYSTEM_LAYER,
            build_oneapi_integration_summary,
        )

        summary = build_oneapi_integration_summary()
        summary.setdefault("system_layer", ONEAPI_SYSTEM_LAYER)
        return summary
    except Exception:
        pass

    # Minimal safe fallback
    try:
        from core.oneapi_system_position import ONEAPI_SYSTEM_LAYER

        return {"system_layer": ONEAPI_SYSTEM_LAYER, "configured": False}
    except Exception:
        return {"system_layer": "aggregator_integration", "configured": False}


def _compile_system_resource() -> Optional[Dict[str, Any]]:
    """Source #4: SystemResourceRegistry health snapshot."""
    try:
        from core.system_resource import get_system_resource_registry

        registry = get_system_resource_registry()
        snapshot = registry.snapshot()
        if snapshot is not None:
            return snapshot.to_dict() if hasattr(snapshot, "to_dict") else None
    except Exception as exc:
        _logger.debug("_compile_system_resource: unavailable: %s", exc)
    return None


def _compile_device_presence() -> Dict[str, Any]:
    """Source #5: Device presence counts from shared route state."""
    try:
        from core.routes._shared import registered_devices, connection_manager

        registered_count = len(registered_devices)
        online_count = len(connection_manager.active_devices)
        return {"registered": registered_count, "online": online_count}
    except Exception as exc:
        _logger.debug("_compile_device_presence: unavailable: %s", exc)
        return {"registered": 0, "online": 0}
