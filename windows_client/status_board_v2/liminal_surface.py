"""
windows_client/status_board_v2/liminal_surface.py
==================================================
LiminalSurface — renders the liminal spatial execution field as part of
Status Board V2.

READ-ONLY surface: displays information only, never sends commands.

Display boundary
----------------
This surface is the **liminal middle-state space** — a spatial execution
field, NOT a second status board.  It must carry only:

1. Local execution chain
2. Cross-device execution chain
3. Sandbox simulation / speculative execution field

It must NOT carry: provider list cards, dashboard-style model panels, full
metrics/status-board panels, or generic operator information blocks.
Those belong exclusively to the right-side desktop status board.

See ``docs/LIMINAL_SPACE_MAPPING.md`` for the canonical mapping definition
and ``docs/DESKTOP_DISPLAY_BOUNDARIES.md`` for the boundary contract.

Architecture
------------
This surface renders the three allowed liminal-space content classes:

* **Local execution chain** — derived from ``LocalChainView``
  (``core.liminal_space_mapping.LocalChainView``)
* **Cross-device execution chain** — derived from ``CrossDeviceChainView``
  (``core.liminal_space_mapping.CrossDeviceChainView``)
* **Sandbox / speculative execution field** — derived from ``SimulationSummary``
  (``core.liminal_space_mapping.SimulationSummary``)

It also maintains the legacy ``desktop_projection`` rendering path for
backward compatibility with the projection engine spatial-dimension bars.

Displayed fields (three-part mapping)
--------------------------------------
**Local chain panel**

- ``total_executions``    : total local executions recorded
- ``canonical_executions``: canonical-path executions
- ``legacy_executions``   : legacy-path executions
- ``last_step``           : most recent chain step reached
- ``is_active``           : whether any executions have been recorded

**Cross-device chain panel**

- ``total_executions``    : total cross-device executions recorded
- ``canonical_executions``: canonical-path executions
- ``legacy_executions``   : legacy-path executions
- ``last_step``           : most recent chain step reached
- ``is_active``           : whether any executions have been recorded

**Sandbox / speculative panel**

- ``simulation_kind``     : ``"speculative"``, ``"sandbox"``, or ``"none"``
- ``is_active``           : whether a simulation is running
- ``candidate_paths``     : candidate execution paths under evaluation
- ``committed_path``      : the committed path (or pending)
- ``step_count``          : simulation steps completed
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ._ansi import BOLD, RESET, c

# Colour coding per phase.
_COLOUR_SILENT = "\033[90m"     # dark grey
_COLOUR_LIMINAL = "\033[33m"    # yellow / amber
_COLOUR_MANIFEST = "\033[32m"   # green
_COLOUR_DIM = "\033[2m"         # dim
_COLOUR_SIM = "\033[35m"        # magenta — speculative/sandbox

_BAR_WIDTH = 18

_PHASE_COLOURS: Dict[str, str] = {
    "silent": _COLOUR_SILENT,
    "liminal": _COLOUR_LIMINAL,
    "manifest": _COLOUR_MANIFEST,
}


def _bar(value: float, width: int = _BAR_WIDTH, colour: str = "") -> str:
    """Render an ASCII progress bar for *value* ∈ [0, 1]."""
    filled = round(max(0.0, min(1.0, value)) * width)
    inner = "█" * filled + "░" * (width - filled)
    bar = f"[{inner}]"
    return c(bar, colour) if colour else bar


class LiminalSurface:
    """Renders the liminal spatial execution field.

    READ-ONLY — this class only produces display strings.

    Renders the three allowed content classes for liminal space:

    1. Local execution chain (path unfolding on-device)
    2. Cross-device execution chain (expansion paths to remote nodes)
    3. Sandbox / speculative execution field (uncommitted branches)

    Uses :mod:`core.liminal_space_mapping` structures for the three-part
    execution mapping.  Falls back to the legacy ``desktop_projection``
    spatial-dimension rendering when the mapping is unavailable.
    """

    def render(self, projection: Dict[str, Any]) -> str:
        """Return a multi-line string for the liminal execution field.

        Parameters
        ----------
        projection:
            A dict conforming to the ``RuntimeProjection`` schema.  Used
            to determine the current phase/domain context and, optionally,
            to derive the legacy spatial-dimension bars.

        Returns
        -------
        str
            Multi-line string ready to print.
        """
        # Attempt to build the three-part liminal space map.
        try:
            from core.liminal_space_mapping import get_liminal_space_map
            lmap = get_liminal_space_map()
            return self._render_three_part(projection, lmap)
        except Exception:  # pragma: no cover
            pass

        # Fallback: legacy desktop_projection spatial-dimension rendering.
        try:
            from desktop_projection import StateSpaceMapper
            liminal = StateSpaceMapper().map(projection)
            return self._render_legacy(liminal)
        except Exception:  # pragma: no cover
            return self._render_unavailable()

    # ------------------------------------------------------------------
    # Three-part rendering (canonical)
    # ------------------------------------------------------------------

    def _render_three_part(
        self,
        projection: Dict[str, Any],
        lmap: Any,
    ) -> str:
        """Render using the three-part liminal space mapping.

        Shows local chain, cross-device chain, and sandbox/speculative
        execution field panels — the three allowed content classes.
        """
        phase = projection.get("tri_state_phase") or "liminal"
        col = _PHASE_COLOURS.get(phase, _COLOUR_DIM)

        local = lmap.local_chain
        cd = lmap.cross_device_chain
        sim = lmap.simulation_summary

        # ── Header ──────────────────────────────────────────────────────
        lines: List[str] = [
            c("  ┌─ Liminal Space — Execution Field ────────────────┐", BOLD),
            f"  │  Phase   : {c(phase, col)}",
        ]

        # ── Panel 1: Local execution chain ──────────────────────────────
        lines.append(c("  │  ── Local Execution Chain ─────────────────────", _COLOUR_DIM))
        if local.is_active:
            local_col = _COLOUR_MANIFEST
            lines.append(
                f"  │   Total   : {c(str(local.total_executions), local_col)}"
                f"  Canonical: {c(str(local.canonical_executions), local_col)}"
                f"  Legacy: {c(str(local.legacy_executions), _COLOUR_DIM)}"
            )
            step_str = local.last_step or "—"
            lines.append(f"  │   Last step: {c(step_str, local_col)}")
        else:
            lines.append(f"  │   {c('(no local executions recorded)', _COLOUR_DIM)}")

        # ── Panel 2: Cross-device execution chain ───────────────────────
        lines.append(c("  │  ── Cross-Device Execution Chain ──────────────", _COLOUR_DIM))
        if cd.is_active:
            cd_col = _COLOUR_LIMINAL
            lines.append(
                f"  │   Total   : {c(str(cd.total_executions), cd_col)}"
                f"  Canonical: {c(str(cd.canonical_executions), cd_col)}"
                f"  Legacy: {c(str(cd.legacy_executions), _COLOUR_DIM)}"
            )
            step_str = cd.last_step or "—"
            device_str = cd.last_device_id or "—"
            lines.append(f"  │   Last step: {c(step_str, cd_col)}  Device: {c(device_str, _COLOUR_DIM)}")
        else:
            lines.append(f"  │   {c('(no cross-device executions recorded)', _COLOUR_DIM)}")

        # ── Panel 3: Sandbox / speculative execution field ───────────────
        lines.append(c("  │  ── Sandbox / Speculative ──────────────────────", _COLOUR_DIM))
        if sim.is_active:
            kind_col = _COLOUR_SIM
            kind_str = sim.simulation_kind.upper() if sim.simulation_kind != "none" else "ACTIVE"
            lines.append(f"  │   Kind    : {c(f'[{kind_str}]', kind_col)}")
            if sim.candidate_paths:
                paths_str = " | ".join(sim.candidate_paths)
                if len(paths_str) > 40:
                    paths_str = paths_str[:37] + "..."
                lines.append(f"  │   Paths   : {c(paths_str, kind_col)}")
            committed = sim.committed_path or c("(pending)", _COLOUR_DIM)
            lines.append(f"  │   Committed: {committed}  Steps: {sim.step_count}")
        else:
            lines.append(f"  │   {c('(no active simulation)', _COLOUR_DIM)}")

        lines.append(c("  └─────────────────────────────────────────────────┘", BOLD))
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Legacy rendering (backward-compatible spatial dimensions)
    # ------------------------------------------------------------------

    @staticmethod
    def _render_legacy(liminal: Any) -> str:
        """Render using legacy desktop_projection spatial dimensions.

        Used as a fallback when the three-part liminal mapping is unavailable.
        Shows depth_factor, topology_visibility, domain_path_emphasis, and
        ambient_intensity as ASCII bars.  These are *projection-engine*
        dimensions, not direct execution-chain views.
        """
        phase = getattr(liminal, "source_phase", "liminal")
        domain = getattr(liminal, "source_domain", None) or "—"
        col = _PHASE_COLOURS.get(phase, _COLOUR_DIM)

        d_bar = _bar(getattr(liminal, "depth_factor", 0.0), colour=col)
        t_bar = _bar(getattr(liminal, "topology_visibility", 0.0), colour=col)
        p_bar = _bar(getattr(liminal, "domain_path_emphasis", 0.0), colour=col)
        a_bar = _bar(getattr(liminal, "ambient_intensity", 0.0), colour=col)

        lines = [
            c("  ┌─ Liminal Projection (legacy) ────────────────────┐", BOLD),
            f"  │  Phase        : {c(phase, col)}  Domain: {c(domain, col)}",
            f"  │  Depth        : {d_bar}  {getattr(liminal, 'depth_factor', 0.0):.3f}",
            f"  │  Topology     : {t_bar}  {getattr(liminal, 'topology_visibility', 0.0):.3f}",
            f"  │  Domain Path  : {p_bar}  {getattr(liminal, 'domain_path_emphasis', 0.0):.3f}",
            f"  │  Ambient      : {a_bar}  {getattr(liminal, 'ambient_intensity', 0.0):.3f}",
            c("  └─────────────────────────────────────────────────┘", BOLD),
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _render_unavailable() -> str:
        """Render a graceful degradation placeholder."""
        return (
            c("  ┌─ Liminal Space — Execution Field ────────────────┐", BOLD) + "\n"
            "  │  (liminal space mapping unavailable)\n"
            + c("  └─────────────────────────────────────────────────┘", BOLD)
        )
