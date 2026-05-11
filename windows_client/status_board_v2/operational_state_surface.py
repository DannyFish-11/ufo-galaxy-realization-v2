from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import _ansi

_BOLD = _ansi.BOLD
_DIM = "\033[90m"
_COLOUR_OK = "\033[32m"
_COLOUR_WARN = "\033[33m"
_COLOUR_ERR = "\033[31m"
_COLOUR_BLUE = "\033[34m"
_COLOUR_CYAN = "\033[36m"
_COLOUR_MAGENTA = "\033[35m"
_UNKNOWN = "unknown"
_DEFAULT_CLIP_LENGTH = 70

# Lifecycle stage display order (observation → admission → readiness → eligibility
# → execution → closure → conditions).  Unlabelled/unknown stage items are appended last.
_STAGE_ORDER = [
    "observation",
    "admission",
    "readiness",
    "eligibility",
    "execution",
    "closure",
    "conditions",
]

_STAGE_LABELS = {
    "observation":  "── Observation ──",
    "admission":    "── Admission ────",
    "readiness":    "── Readiness ────",
    "eligibility":  "── Eligibility ──",
    "execution":    "── Execution ────",
    "closure":      "── Closure ──────",
    "conditions":   "── Conditions ───",
}

# State-value colour coding for the terminal.
_DEGRADED_STATES = {
    "degraded", "degraded_visible", "degraded_operation", "degraded_partial",
    "recovery_active", "compat", "incomplete",
}
_BLOCKED_STATES = {
    "blocked", "present", "unavailable", "absent",
}
_OK_STATES = {
    "ready", "available", "active", "eligible", "complete", "continuous",
    "acceptable", "canonical_operation", "canonical", "visible", "satisfied",
}
_WARN_STATES = {
    "acceptable_degraded", "waiting_dependency", "partial", "idle", "pending",
}

# Source-of-truth boundary short labels.
_BOUNDARY_SHORT = {
    "v2_authoritative":         "V2",
    "android_originated":       "AND",
    "joint_cross_repo_derived": "JOINT",
}


def _clip(value: str, max_len: int = _DEFAULT_CLIP_LENGTH) -> str:
    return value if len(value) <= max_len else value[: max_len - 1] + "…"


def _state_colour(state: str) -> str:
    """Return an ANSI colour code appropriate for the given state value."""
    lower = state.lower()
    if lower in _OK_STATES:
        return _COLOUR_OK
    if lower in _DEGRADED_STATES:
        return _COLOUR_WARN
    if lower in _BLOCKED_STATES:
        return _COLOUR_ERR
    if "not_applicable" in lower:
        return _DIM
    return ""


class OperationalStateSurface:
    """Render the authoritative operational state board panel.

    PR-D productization:
    - Categories are grouped by lifecycle stage (observation → admission →
      readiness → eligibility → execution → closure → conditions).
    - Each category shows its source-of-truth boundary (V2 / AND / JOINT).
    - State values are colour-coded: green=ok, yellow=degraded/warn,
      red=blocked/absent.
    - The header shows the lifecycle-stage index so the operator can see
      at a glance which stages are populated.
    - Degraded and recovery states are surfaced as first-class indicators
      rather than collapsed into a single colour.
    """

    def render(self, projection: Dict[str, Any]) -> str:
        board = projection.get("operational_state_board") or {}
        categories = board.get("categories") or []
        if not categories:
            return "\n".join(
                [
                    _ansi.c("  ┌─ Operational State Board ───────────────────┐", _BOLD),
                    f"  │  {_ansi.c('No unified operational state contract attached.', _DIM)}",
                    _ansi.c("  └──────────────────────────────────────────────┘", _BOLD),
                ]
            )

        lines: List[str] = [
            _ansi.c("  ┌─ Operational State Board ───────────────────┐", _BOLD),
            f"  │  Contract : {_clip(str(board.get('authority') or _UNKNOWN))}",
            f"  │  Version  : {board.get('contract_version') or _UNKNOWN}",
        ]

        # Group categories by lifecycle stage.
        by_stage: Dict[str, List[Dict[str, Any]]] = {stage: [] for stage in _STAGE_ORDER}
        unclassified: List[Dict[str, Any]] = []
        for item in categories:
            stage = item.get("lifecycle_stage") or ""
            if stage in by_stage:
                by_stage[stage].append(item)
            else:
                unclassified.append(item)

        # Render each stage group in order.
        for stage in _STAGE_ORDER:
            items = by_stage[stage]
            if not items:
                continue
            stage_label = _STAGE_LABELS.get(stage, f"── {stage} ──")
            lines.append(f"  │  {_ansi.c(stage_label, _COLOUR_CYAN)}")
            for item in items:
                _render_category_item(lines, item)

        # Render any items without a lifecycle stage last.
        if unclassified:
            lines.append(f"  │  {_ansi.c('── Other ────────', _DIM)}")
            for item in unclassified:
                _render_category_item(lines, item)

        # Dependencies and blockers summary.
        deps = board.get("dependencies_and_blockers") or {}
        blocked = bool(deps.get("blocked"))
        incomplete = bool(deps.get("incomplete"))
        waiting = ", ".join(deps.get("waiting_dependencies") or []) or "none"
        lines.append(
            f"  │  {_ansi.c('── Conditions ───', _COLOUR_CYAN)}"
            if not any(by_stage.get("conditions")) and not unclassified
            else f"  │  {_ansi.c('conditions summary:', _DIM)}"
        )
        lines.append(
            f"  │    Blocked    : {_ansi.c('YES', _COLOUR_ERR) if blocked else _ansi.c('no', _COLOUR_OK)}"
        )
        lines.append(
            f"  │    Incomplete : {_ansi.c('YES', _COLOUR_WARN) if incomplete else _ansi.c('no', _COLOUR_OK)}"
        )
        lines.append(f"  │    Waiting    : {_clip(waiting)}")

        lines.append(_ansi.c("  └──────────────────────────────────────────────┘", _BOLD))
        return "\n".join(lines)


def _render_category_item(lines: List[str], item: Dict[str, Any]) -> None:
    """Append one category entry to the board lines list."""
    label = str(item.get("label") or item.get("category_id") or "state")
    state = str(item.get("state") or _UNKNOWN)
    boundary_raw = str(item.get("source_of_truth_boundary") or "")
    boundary = _BOUNDARY_SHORT.get(boundary_raw, boundary_raw[:5] or "?")
    summary = _clip(str(item.get("summary") or ""))
    colour = _state_colour(state)

    state_str = _ansi.c(state, colour) if colour else state
    lines.append(f"  │   [{boundary}] {label}: {state_str}")
    if summary:
        lines.append(f"  │         {_ansi.c(summary, _DIM)}")
