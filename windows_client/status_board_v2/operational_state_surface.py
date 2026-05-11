from __future__ import annotations

from typing import Any, Dict, List

from . import _ansi

_BOLD = _ansi.BOLD
_DIM = "\033[90m"
_UNKNOWN = "unknown"


def _clip(value: str, max_len: int = 76) -> str:
    return value if len(value) <= max_len else value[: max_len - 1] + "…"


class OperationalStateSurface:
    """Render the authoritative operational state board panel."""

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
        for item in categories:
            label = str(item.get("label") or item.get("category_id") or "state")
            state = str(item.get("state") or _UNKNOWN)
            boundary = str(item.get("source_of_truth_boundary") or _UNKNOWN)
            summary = _clip(str(item.get("summary") or ""))
            lines.append(f"  │  • {label}: {state} [{boundary}]")
            if summary:
                lines.append(f"  │    why: {summary}")
        deps = board.get("dependencies_and_blockers") or {}
        waiting = ", ".join(deps.get("waiting_dependencies") or []) or "none"
        lines.append(f"  │  Blocked   : {bool(deps.get('blocked'))}")
        lines.append(f"  │  Incomplete: {bool(deps.get('incomplete'))}")
        lines.append(f"  │  Waiting   : {_clip(waiting)}")
        lines.append(_ansi.c("  └──────────────────────────────────────────────┘", _BOLD))
        return "\n".join(lines)
