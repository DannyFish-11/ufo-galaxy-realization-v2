"""
core/startup_tier_model.py — Startup-tier model authority.

Defines the canonical 3-tier startup model and the active-node runtime-readiness
baseline for the Galaxy repository.

This module is a governance and validation authority — it does **not** introduce
a new launcher system.  All tier definitions are derived from the existing
``startup_policy`` and ``group`` metadata in ``node_dependencies.json`` and the
helpers already present in ``launcher/node_startup.py``.

Tier Model
----------
- **Core**     — minimum canonical runtime boot
                 ``startup_policy="active"`` AND ``group="core"``
- **Standard** — normal development/functional boot
                 ``startup_policy="active"`` AND
                 ``group`` in ``{"core", "development"}``
- **Full**     — all active nodes + governed optional nodes;
                 broad runtime boot
                 ``startup_policy`` in ``{"active", "optional"}``

Invariant: Core ⊂ Standard ⊂ Full (strict superset chain).

Active-Node Readiness Baseline
-------------------------------
For a node to be considered part of the **active baseline** it must:

1. Carry ``startup_policy: "active"`` in ``node_dependencies.json``.
2. Have ``main.py`` present on disk.
3. Have ``fusion_entry.py`` present on disk.

Nodes that are active but missing ``fusion_entry.py`` are **readiness gaps** —
they are governance issues requiring remediation before the node can be
considered production-ready.

Optional nodes that satisfy checks 2–3 are **governed optional** — they have a
tracked path toward ``active`` but are not yet part of the baseline.

Sentinels
---------
``STARTUP_TIER_MODEL_AUTHORITY``    — This module is the authority for the
                                      tier model definition.
``STARTUP_TIER_MODEL_GROUNDED_IN_EXISTING_GOVERNANCE``
                                   — Tier selection rules derive exclusively
                                     from existing startup_policy + group
                                     metadata; no parallel config authority.
``ACTIVE_NODE_READINESS_BASELINE_DEFINED``
                                   — A compact, checkable baseline exists for
                                     active nodes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

STARTUP_TIER_MODEL_AUTHORITY = "core.startup_tier_model"
STARTUP_TIER_MODEL_GROUNDED_IN_EXISTING_GOVERNANCE = True
ACTIVE_NODE_READINESS_BASELINE_DEFINED = True

# ---------------------------------------------------------------------------
# Tier constants (mirrors launcher/node_startup.py)
# ---------------------------------------------------------------------------

TIER_CORE = "Core"
TIER_STANDARD = "Standard"
TIER_FULL = "Full"

TIER_DESCRIPTIONS: Dict[str, str] = {
    TIER_CORE: (
        "Minimum canonical runtime boot. "
        "All active nodes whose group is 'core'. "
        "System cannot be considered runnable if any Core-tier node fails."
    ),
    TIER_STANDARD: (
        "Normal development and functional boot. "
        "Active nodes in groups 'core' and 'development'. "
        "Core failures remain blocking; standard-only failures degrade capability."
    ),
    TIER_FULL: (
        "Broad runtime boot — all active and governed optional nodes. "
        "Mirrors the full production node surface. "
        "Optional-node failures are tolerated (soft-fail)."
    ),
}

TIER_SELECTION_RULES: Dict[str, str] = {
    TIER_CORE: 'startup_policy == "active" AND group == "core"',
    TIER_STANDARD: 'startup_policy == "active" AND group in {"core", "development"}',
    TIER_FULL: 'startup_policy in {"active", "optional"}',
}

TIER_ACCEPTANCE_CRITERIA: Dict[str, str] = {
    TIER_CORE: "All Core-tier nodes must start successfully.",
    TIER_STANDARD: "All Standard-tier nodes must start; Core failures remain blocking.",
    TIER_FULL: (
        "All active nodes must start; optional node failures tolerated (soft-fail). "
        "Nodes with startup_policy='skip' are never started."
    ),
}

# ---------------------------------------------------------------------------
# Readiness baseline dataclass
# ---------------------------------------------------------------------------


@dataclass
class ActiveNodeReadinessBaseline:
    """Compact active-node runtime-readiness baseline.

    Attributes
    ----------
    core_tier:
        Nodes in the Core startup tier.
    standard_tier:
        Nodes in the Standard startup tier.
    active_baseline:
        Active nodes that satisfy the minimum readiness bar
        (main.py + fusion_entry.py present on disk).
    optional_governed:
        Optional nodes that meet the structural bar
        (main.py + fusion_entry.py present) — governed, tracked toward active.
    readiness_gaps:
        Active nodes missing ``fusion_entry.py``.  These are governance gaps
        requiring remediation.
    """

    core_tier: List[str] = field(default_factory=list)
    standard_tier: List[str] = field(default_factory=list)
    active_baseline: List[str] = field(default_factory=list)
    optional_governed: List[str] = field(default_factory=list)
    readiness_gaps: List[str] = field(default_factory=list)

    @property
    def core_tier_count(self) -> int:
        return len(self.core_tier)

    @property
    def standard_tier_count(self) -> int:
        return len(self.standard_tier)

    @property
    def active_baseline_count(self) -> int:
        return len(self.active_baseline)

    @property
    def optional_governed_count(self) -> int:
        return len(self.optional_governed)

    @property
    def readiness_gap_count(self) -> int:
        return len(self.readiness_gaps)

    def is_core_complete(self) -> bool:
        """True when no Core-tier node has a readiness gap."""
        core_set = set(self.core_tier)
        return not any(n in core_set for n in self.readiness_gaps)

    def summary(self) -> Dict[str, int]:
        return {
            "core_tier_count": self.core_tier_count,
            "standard_tier_count": self.standard_tier_count,
            "active_baseline_count": self.active_baseline_count,
            "optional_governed_count": self.optional_governed_count,
            "readiness_gap_count": self.readiness_gap_count,
        }


# ---------------------------------------------------------------------------
# Runtime readiness check
# ---------------------------------------------------------------------------

def build_readiness_baseline(
    nodes_dir: Optional[Path] = None,
    node_configs: Optional[Dict] = None,
) -> ActiveNodeReadinessBaseline:
    """Build the active-node readiness baseline from disk state.

    This function is intentionally standalone — it does not import the
    launcher (to avoid circular imports) and can be called from scripts
    and tests without a live system.

    Args:
        nodes_dir:   Path to the ``nodes/`` directory.  Defaults to the
                     canonical location relative to this file.
        node_configs: Pre-loaded mapping of node names to their config
                      dicts (from ``node_dependencies.json``).  Loaded
                      automatically when not provided.

    Returns:
        :class:`ActiveNodeReadinessBaseline` populated from current disk state.
    """
    project_root = Path(__file__).parent.parent
    if nodes_dir is None:
        nodes_dir = project_root / "nodes"
    if node_configs is None:
        ndj_path = project_root / "node_dependencies.json"
        if ndj_path.exists():
            with ndj_path.open(encoding="utf-8") as f:
                data = json.load(f)
            node_configs = data.get("nodes", {})
        else:
            node_configs = {}

    core_tier: List[str] = []
    standard_tier: List[str] = []
    active_baseline: List[str] = []
    optional_governed: List[str] = []
    readiness_gaps: List[str] = []

    _core_groups = {"core"}
    _standard_groups = {"core", "development"}

    for name, cfg in node_configs.items():
        if not isinstance(cfg, dict):
            continue
        policy = cfg.get("startup_policy", "active")
        group = cfg.get("group", "")
        node_dir = nodes_dir / name
        has_main = (node_dir / "main.py").exists()
        has_fusion = (node_dir / "fusion_entry.py").exists()

        # Tier membership (policy-gated, disk-presence required)
        if policy == "active" and has_main:
            if group in _core_groups:
                core_tier.append(name)
            if group in _standard_groups:
                standard_tier.append(name)

        # Readiness baseline
        if policy == "active" and has_main:
            if has_fusion:
                active_baseline.append(name)
            else:
                readiness_gaps.append(name)
        elif policy == "optional" and has_main and has_fusion:
            optional_governed.append(name)

    return ActiveNodeReadinessBaseline(
        core_tier=sorted(core_tier),
        standard_tier=sorted(standard_tier),
        active_baseline=sorted(active_baseline),
        optional_governed=sorted(optional_governed),
        readiness_gaps=sorted(readiness_gaps),
    )


def check_tier_model_metadata(ndj_data: Optional[Dict] = None) -> Dict[str, bool]:
    """Validate that ``node_dependencies.json`` contains the tier-model metadata.

    Args:
        ndj_data: Pre-loaded JSON dict.  Loaded from disk when not provided.

    Returns:
        Dict mapping check names to bool pass/fail results.
    """
    if ndj_data is None:
        ndj_path = Path(__file__).parent.parent / "node_dependencies.json"
        if not ndj_path.exists():
            return {"node_dependencies_exists": False}
        with ndj_path.open(encoding="utf-8") as f:
            ndj_data = json.load(f)

    meta = ndj_data.get("_startup_tier_model", {})
    tiers = meta.get("tiers", {})

    return {
        "metadata_key_present": "_startup_tier_model" in ndj_data,
        "all_three_tiers_defined": all(t in tiers for t in (TIER_CORE, TIER_STANDARD, TIER_FULL)),
        "core_tier_has_selection_rule": bool(tiers.get(TIER_CORE, {}).get("selection_rule")),
        "standard_tier_has_selection_rule": bool(tiers.get(TIER_STANDARD, {}).get("selection_rule")),
        "full_tier_has_selection_rule": bool(tiers.get(TIER_FULL, {}).get("selection_rule")),
        "invariants_listed": bool(meta.get("invariants")),
    }
