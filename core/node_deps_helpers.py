"""
core/node_deps_helpers.py — Canonical node metadata reader
===========================================================

Reads ``node_dependencies.json`` (the **single canonical static metadata
source** for all node definitions) and exposes helper utilities used by the
capability bus, discovery service, and dispatcher.

``node_dependencies.json`` is the sole authority for:
  - which nodes belong to the active system
  - startup policy (active / optional / skip)
  - port assignments
  - dependency topology
  - architectural group

Other files such as ``config/node_registry.json`` are **generated
compatibility artifacts** that must not be treated as peer authorities.
They can be regenerated at any time via ``scripts/gen_node_registry.py``.

Sentinel
--------
``NODE_METADATA_SSOT_IS_NODE_DEPENDENCIES_JSON`` — programmatic assertion
that ``node_dependencies.json`` is the authoritative node-metadata source.
"""

from __future__ import annotations

import json
import re
import logging
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

#: Asserts that ``node_dependencies.json`` is the single canonical static
#: metadata source for all node definitions.
#:
#: Port, startup policy, dependency topology, and architectural group all
#: resolve from this file.  ``config/node_registry.json`` is a generated
#: compatibility artifact and must not be treated as a peer authority.
NODE_METADATA_SSOT_IS_NODE_DEPENDENCIES_JSON: str = (
    "NODE_METADATA_SSOT::node_dependencies.json is the single canonical "
    "static metadata source for node port, startup_policy, dependencies, "
    "and group.  config/node_registry.json is a generated compat artifact only."
)

# ---------------------------------------------------------------------------
# File location
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_NODE_DEPS_PATH = _PROJECT_ROOT / "node_dependencies.json"

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_NODE_KEY_RE = re.compile(r"^Node_(\d+)_(.+)$")


def _parse_node_key(node_key: str) -> Tuple[str, str]:
    """Extract ``(numeric_id, short_name)`` from a canonical node key.

    Examples::

        "Node_00_StateMachine"  → ("00", "StateMachine")
        "Node_100_MemorySystem" → ("100", "MemorySystem")
        "anything_else"         → ("", "anything_else")
    """
    m = _NODE_KEY_RE.match(node_key)
    if m:
        return m.group(1), m.group(2)
    return "", node_key


def _policy_to_status(startup_policy: str) -> str:
    """Map ``startup_policy`` to a legacy ``status`` string.

    ``"active"`` / ``"optional"`` → ``"active"``
    ``"skip"``                    → ``"skip"``
    anything else                 → ``"unknown"``
    """
    if startup_policy in ("active", "optional"):
        return "active"
    if startup_policy == "skip":
        return "skip"
    return "unknown"


def _policy_to_production_ready(startup_policy: str) -> bool:
    """Return ``True`` only for ``startup_policy="active"`` nodes."""
    return startup_policy == "active"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_node_deps(path: Optional[Path] = None) -> Dict:
    """Load and return the raw ``node_dependencies.json`` data dict.

    Parameters
    ----------
    path:
        Override the file path.  Defaults to the project-root
        ``node_dependencies.json``.

    Returns
    -------
    dict
        Full parsed JSON.  Returns ``{}`` on error.
    """
    p = Path(path) if path else _NODE_DEPS_PATH
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        logger.warning("node_deps_helpers: file not found: %s", p)
    except Exception as exc:
        logger.warning("node_deps_helpers: error reading %s: %s", p, exc)
    return {}


def iter_active_node_metadata(
    path: Optional[Path] = None,
    *,
    include_skip: bool = False,
) -> Iterator[Tuple[str, Dict]]:
    """Iterate ``(node_key, enriched_metadata)`` from ``node_dependencies.json``.

    Each yielded ``enriched_metadata`` dict contains the original fields from
    ``node_dependencies.json`` plus derived compatibility fields:

    * ``id``               — numeric string extracted from *node_key*
    * ``name``             — short name extracted from *node_key*
    * ``status``           — derived from ``startup_policy``
    * ``production_ready`` — ``True`` only for ``startup_policy="active"``
    * ``path``             — ``"nodes/<node_key>"``

    Parameters
    ----------
    path:
        Override file path.  Defaults to project-root
        ``node_dependencies.json``.
    include_skip:
        When ``True``, nodes with ``startup_policy="skip"`` are included.
        Defaults to ``False`` (skip-policy nodes are excluded from active set).

    Yields
    ------
    (node_key, metadata_dict)
    """
    data = load_node_deps(path)
    nodes: Dict = data.get("nodes", {})

    for node_key, raw_cfg in nodes.items():
        if not isinstance(raw_cfg, dict):
            continue
        policy = raw_cfg.get("startup_policy", "active")
        if not include_skip and policy == "skip":
            continue
        node_id, short_name = _parse_node_key(node_key)
        meta = dict(raw_cfg)
        meta.setdefault("id", node_id)
        meta.setdefault("name", short_name)
        meta["status"] = _policy_to_status(policy)
        meta["production_ready"] = _policy_to_production_ready(policy)
        meta.setdefault("path", f"nodes/{node_key}")
        yield node_key, meta


def build_node_id_to_key_map(path: Optional[Path] = None) -> Dict[str, str]:
    """Return ``{numeric_id: node_key}`` for all non-skip nodes.

    Used by ``_find_node_key(node_id)`` helpers that need to map a short
    numeric ID (e.g. ``"00"``) back to the full canonical key
    (e.g. ``"Node_00_StateMachine"``).
    """
    return {
        meta["id"]: node_key
        for node_key, meta in iter_active_node_metadata(path, include_skip=True)
        if meta.get("id")
    }
