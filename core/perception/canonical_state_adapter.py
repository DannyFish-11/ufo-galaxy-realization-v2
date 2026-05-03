"""PR-24: Canonical state adapter — normalised access to canonical state contracts.

This module provides :class:`CanonicalStateAdapter`, a lightweight helper that
extracts **canonical** state contracts from an OpenClawd response metadata dict.

Design intent
-------------
After PR-16 ~ PR-23 introduced the canonical state contracts
(:class:`~core.perception.canonical_perception_state.CanonicalPerceptionState`,
:class:`~core.model_topology.canonical_model_supply_state.CanonicalModelSupplyState`,
:class:`~core.schemas.unified_control_plan.UnifiedControlPlan`, and the
desktop status projection), the response metadata dict may also contain
*deprecated-compat* duplicate fields that remain only for backward
compatibility:

* ``multimodal_context`` — raw fused dict; prefer ``canonical_perception_state``
* ``multimodal_route_decision`` (top-level) — prefer
  ``unified_control_plan["multimodal_route_decision"]``

:class:`CanonicalStateAdapter` provides a single place to enforce the
**canonical read order**:

1. Prefer the canonical field/key.
2. Fall back to the deprecated-compat field only when the canonical one is
   absent (e.g. for very old compatibility callers).
3. Never create a new parallel state representation.

Usage example::

    adapter = CanonicalStateAdapter(response.get("metadata", {}))

    perception = adapter.canonical_perception_state()   # canonical
    ucp        = adapter.unified_control_plan()         # canonical
    route      = adapter.multimodal_route_decision()    # from UCP (canonical)
    supply     = adapter.canonical_model_supply_summary()  # from UCP (canonical)

Architectural boundaries
------------------------
* This adapter is **read-only** — it never mutates state.
* It is safe to use from both the runtime shell and from test harnesses.
* It does **not** import OpenClawd or DesktopPresenceRuntime to avoid circular
  dependencies; it operates purely on plain dicts.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class CanonicalStateAdapter:
    """Read canonical state contracts from an OpenClawd response metadata dict.

    Parameters
    ----------
    metadata:
        The ``metadata`` dict attached to an OpenClawd response.  May be an
        empty dict or ``None`` — all methods degrade gracefully.
    """

    def __init__(self, metadata: Optional[Dict[str, Any]] = None) -> None:
        self._meta: Dict[str, Any] = metadata or {}

    # ------------------------------------------------------------------
    # Canonical perception state
    # ------------------------------------------------------------------

    def canonical_perception_state(self) -> Optional[Dict[str, Any]]:
        """Return the canonical perception state dict.

        **Canonical source**: ``metadata["canonical_perception_state"]``
        (set by :meth:`~core.openclawd.OpenClawd._build_canonical_perception_state`).

        The deprecated ``metadata["multimodal_context"]`` field is **not**
        used by this method; it exists only for external backward compatibility.

        Returns ``None`` when no perception state was produced (e.g. text-only
        requests where ``_build_canonical_perception_state`` was not reached).
        """
        return self._meta.get("canonical_perception_state")

    def has_multimodal_perception(self) -> bool:
        """Return ``True`` when the canonical perception state signals active
        multimodal modalities beyond plain text."""
        cps = self.canonical_perception_state()
        if cps is None:
            return False
        modalities: List[str] = cps.get("active_modalities") or []
        # Any modality other than plain text signals multimodal perception
        non_text = set(modalities) - {"text"}
        return bool(non_text)

    def requires_native_multimodal(self) -> bool:
        """Return ``True`` when the canonical perception state requires a
        native multimodal model."""
        cps = self.canonical_perception_state()
        if cps is None:
            return False
        return bool(cps.get("requires_native_multimodal", False))

    # ------------------------------------------------------------------
    # Unified control plan
    # ------------------------------------------------------------------

    def unified_control_plan(self) -> Optional[Dict[str, Any]]:
        """Return the canonical unified control plan dict.

        **Canonical source**: ``metadata["unified_control_plan"]`` (set by
        :meth:`~core.openclawd.OpenClawd._build_unified_control_plan`).

        Returns ``None`` when the plan was not built (e.g. an internal error
        prevented plan construction).
        """
        return self._meta.get("unified_control_plan")

    def plan_id(self) -> Optional[str]:
        """Return the canonical plan identifier, or ``None``."""
        ucp = self.unified_control_plan()
        return ucp.get("plan_id") if ucp else None

    def decision_posture(self) -> Optional[str]:
        """Return the canonical decision posture string, or ``None``."""
        ucp = self.unified_control_plan()
        return ucp.get("decision_posture") if ucp else None

    # ------------------------------------------------------------------
    # Canonical model supply summary (from UCP)
    # ------------------------------------------------------------------

    def canonical_model_supply_summary(self) -> Optional[Dict[str, Any]]:
        """Return the canonical model supply summary embedded in the UCP.

        **Canonical source**:
        ``unified_control_plan["canonical_model_supply_summary"]``

        Returns ``None`` when not present (e.g. supply state was not built).
        """
        ucp = self.unified_control_plan()
        return ucp.get("canonical_model_supply_summary") if ucp else None

    # ------------------------------------------------------------------
    # Multimodal routing decision (canonical: from UCP; compat: top-level)
    # ------------------------------------------------------------------

    def multimodal_route_decision(self) -> Optional[Dict[str, Any]]:
        """Return the canonical multimodal routing decision.

        **Canonical source** (PR-24):
        ``unified_control_plan["multimodal_route_decision"]``

        **Deprecated-compat fallback**:
        ``metadata["multimodal_route_decision"]`` — used only when the
        canonical source is absent (old responses without PR-24 data).

        New consumers should always use this method rather than reading
        ``metadata["multimodal_route_decision"]`` directly.
        """
        ucp = self.unified_control_plan()
        if ucp is not None:
            route = ucp.get("multimodal_route_decision")
            if route is not None:
                return route
        # Deprecated-compat fallback: top-level metadata key (pre-PR-24)
        return self._meta.get("multimodal_route_decision")

    def is_native_multimodal_route(self) -> bool:
        """Return ``True`` when the routing decision selected a native
        multimodal tier."""
        route = self.multimodal_route_decision()
        if route is None:
            return False
        return bool(route.get("is_native_multimodal", False))

    def route_type(self) -> Optional[str]:
        """Return the routing tier label (e.g. ``"native_multimodal"``,
        ``"partial_multimodal"``, ``"advisory"``), or ``None``."""
        route = self.multimodal_route_decision()
        return route.get("route_type") if route else None

    # ------------------------------------------------------------------
    # Execution decision helpers (from UCP)
    # ------------------------------------------------------------------

    def execution_path(self) -> Optional[str]:
        """Return the canonical execution path string from the UCP, or
        ``None``."""
        ucp = self.unified_control_plan()
        if ucp is None:
            return None
        ued = ucp.get("unified_execution_decision")
        if isinstance(ued, dict):
            return ued.get("execution_path")
        ced = ucp.get("chosen_execution_decision")
        if isinstance(ced, dict):
            return ced.get("execution_path")
        return None

    def fallback_level(self) -> Optional[str]:
        """Return the canonical fallback level from the UCP, or ``None``."""
        ucp = self.unified_control_plan()
        return ucp.get("fallback_level") if ucp else None

    def has_fallback(self) -> bool:
        """Return ``True`` when the UCP signals any fallback/downgrade."""
        ucp = self.unified_control_plan()
        if ucp is None:
            return False
        fdr = ucp.get("fallback_decision_record")
        if isinstance(fdr, dict):
            return bool(fdr.get("has_fallback", False))
        return ucp.get("fallback_level", "none") not in ("none", None, "")

    # ------------------------------------------------------------------
    # Deprecated-compat field access (explicit, for migration tracking)
    # ------------------------------------------------------------------

    def multimodal_context_compat(self) -> Optional[Dict[str, Any]]:
        """Return the deprecated ``multimodal_context`` dict.

        .. deprecated:: PR-24
            This field is a raw fused context dict retained only for
            backward compatibility.  It was deprecated in PR-24 in favour of
            ``canonical_perception_state`` (the canonical source of truth).
            Prefer :meth:`canonical_perception_state` for all new consumers.
            Do **not** add new call sites that read this field.
            This compat accessor may be removed in a future cleanup PR.
        """
        return self._meta.get("multimodal_context")

    def perception_boundary_summary(self) -> Dict[str, Any]:
        """Return the governed perception fact-boundary summary."""

        try:
            from core.perception.perception_fact_boundary import (
                build_perception_fact_boundary_summary,
            )

            return build_perception_fact_boundary_summary(self._meta)
        except Exception:
            return {
                "canonical_fact_surface": "response.metadata.canonical_perception_state",
                "canonical_fact_present": self.canonical_perception_state() is not None,
                "compat_surfaces_present": (
                    ["response.metadata.multimodal_context"]
                    if self.multimodal_context_compat() is not None
                    else []
                ),
            }

    # ------------------------------------------------------------------
    # Convenience: validate canonical state presence
    # ------------------------------------------------------------------

    def has_canonical_perception(self) -> bool:
        """Return ``True`` when a canonical perception state is present."""
        return self.canonical_perception_state() is not None

    def has_unified_control_plan(self) -> bool:
        """Return ``True`` when a unified control plan is present."""
        return self.unified_control_plan() is not None

    def canonical_state_summary(self) -> Dict[str, Any]:
        """Return a compact dict summarising canonical state availability.

        Useful for diagnostics, logging, and test assertions.  All values
        are safe for JSON serialisation.
        """
        ucp = self.unified_control_plan()
        return {
            "has_canonical_perception": self.has_canonical_perception(),
            "has_unified_control_plan": self.has_unified_control_plan(),
            "plan_id": self.plan_id(),
            "decision_posture": self.decision_posture(),
            "execution_path": self.execution_path(),
            "fallback_level": self.fallback_level(),
            "has_fallback": self.has_fallback(),
            "route_type": self.route_type(),
            "is_native_multimodal_route": self.is_native_multimodal_route(),
            "requires_native_multimodal": self.requires_native_multimodal(),
            "has_model_supply_summary": self.canonical_model_supply_summary() is not None,
            # Deprecated-compat presence flags (for audit/migration tracking)
            "compat_multimodal_context_present": self.multimodal_context_compat() is not None,
            "compat_top_level_route_present": self._meta.get("multimodal_route_decision") is not None,
            # Canonical routing embedded in UCP (PR-24)
            "canonical_route_in_ucp": (
                ucp.get("multimodal_route_decision") is not None if ucp else False
            ),
            "perception_boundary": self.perception_boundary_summary(),
        }
