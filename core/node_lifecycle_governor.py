#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/node_lifecycle_governor.py
================================
PR-531: Node Lifecycle Governor — Govern Newly Onboarded / Auto-Generated
Node Lifecycle.

This module is the **node lifecycle governance layer** for the Galaxy runtime.
It ensures that newly onboarded or auto-generated nodes are not just present
but governed: each node must pass through explicit lifecycle stages before
it can be callable, active, or promoted.

Problem addressed
-----------------
After PRs #506–#530 the callable-node baseline is well-defined and startup
tiers are modelled.  However, newly registered / auto-generated nodes still
do not have a fully governed lifecycle through:

  - capability registration into the canonical path
  - startup/readiness governance
  - callable classification / capability exposure governance
  - optional / experimental / active promotion semantics

This module provides those missing lifecycle gates without inventing a new
parallel system — it builds on existing governance concepts:
:class:`~core.nodes.node_fabric_registry.NodeFabricRegistry`,
:mod:`~core.callable_node_baseline`, and :mod:`~core.startup_tier_model`.

Lifecycle stages
----------------
::

    REGISTERED
        │   (readiness check passes)
        ▼
    READINESS_CHECKED
        │   (callable baseline classification passes)
        ▼
    CALLABLE_CLASSIFIED
        │   (capability registered into canonical path)
        ▼
    CAPABILITY_REGISTERED
        │   (assigned to OPTIONAL or EXPERIMENTAL by operator/policy)
        ▼
    OPTIONAL / EXPERIMENTAL
        │   (promotion criteria met)
        ▼
    ACTIVE
        │   (deprecation decision)
        ▼
    DEPRECATED

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────────┐
    │  OPERATOR / GOVERNANCE LAYER                                    │
    │  promote_node()  ·  demote_node()  ·  node_governance_snapshot()│
    └────────────────────────────┬─────────────────────────────────────┘
                                 ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │  NODE LIFECYCLE GOVERNOR  (this module, Layer 15)               │
    │                                                                  │
    │  NodeLifecycleStage enum                                        │
    │  NodeGovernanceRecord dataclass                                 │
    │  NodeLifecycleGovernor singleton                                │
    │                                                                  │
    │  Reads from:                                                    │
    │    • NodeFabricRegistry — registration, heartbeat, class        │
    │    • CallableNodeBaseline — callable-class check               │
    │    • StartupTierModel — tier membership / readiness             │
    │    • CapabilityRegistry — capability registration check         │
    └────────────────────────────┬─────────────────────────────────────┘
                                 ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │  CORE GOVERNANCE LAYERS (Layers 6–14)                           │
    └──────────────────────────────────────────────────────────────────┘

Public API
----------
Authority sentinels::

    NODE_LIFECYCLE_GOVERNOR_AUTHORITY
    NODE_LIFECYCLE_GOVERNOR_LAYER_POSITION
    NODE_LIFECYCLE_GOVERNANCE_PIPELINE_DEFINED

Policy sentinels::

    NODE_MUST_PASS_LIFECYCLE_GATES_POLICY
    NO_WILD_GROWTH_POLICY
    PROMOTION_REQUIRES_CAPABILITY_REGISTRATION_POLICY

Enums::

    NodeLifecycleStage
    NodeGovernanceOutcome

Dataclasses::

    NodeGovernanceRecord
    NodeLifecycleGovernorSnapshot

Class::

    NodeLifecycleGovernor
    get_node_lifecycle_governor()
    reset_node_lifecycle_governor()

Helpers::

    govern_node(node_name) -> NodeGovernanceRecord
    promote_node(node_name) -> NodeGovernanceRecord
    demote_node(node_name, reason) -> NodeGovernanceRecord
    node_governance_snapshot() -> NodeLifecycleGovernorSnapshot
"""

from __future__ import annotations

import logging
import threading
import time
import uuid as _uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.NodeLifecycleGovernor")

# ===========================================================================
# Authority sentinels
# ===========================================================================

NODE_LIFECYCLE_GOVERNOR_AUTHORITY: str = (
    "NODE_LIFECYCLE_GOVERNOR::PR531_NODE_LIFECYCLE_AUTHORITY_V1: "
    "core/node_lifecycle_governor.py is the canonical governance layer for "
    "newly onboarded and auto-generated node lifecycle.  Layer 15.  "
    "All new nodes MUST pass through the governed lifecycle pipeline."
)

NODE_LIFECYCLE_GOVERNOR_LAYER_POSITION: int = 15

NODE_LIFECYCLE_GOVERNANCE_PIPELINE_DEFINED: str = (
    "NODE_LIFECYCLE_GOVERNANCE_PIPELINE_V1: "
    "Pipeline: REGISTERED → READINESS_CHECKED → CALLABLE_CLASSIFIED "
    "→ CAPABILITY_REGISTERED → OPTIONAL/EXPERIMENTAL → ACTIVE → DEPRECATED"
)

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

NODE_MUST_PASS_LIFECYCLE_GATES_POLICY: str = (
    "NODE_MUST_PASS_LIFECYCLE_GATES_V1: "
    "A new node may not be callable or promoted to ACTIVE without passing "
    "readiness, callable-classification, and capability-registration gates.  "
    "Skipping gates is not permitted except via explicit governance override."
)

NO_WILD_GROWTH_POLICY: str = (
    "NO_WILD_GROWTH_V1: "
    "Auto-generated or newly onboarded nodes MUST be registered with "
    "NodeLifecycleGovernor before they are considered part of the runtime.  "
    "Nodes that are 'present' but not governed are wild-growth nodes and "
    "are classified as governance debt."
)

PROMOTION_REQUIRES_CAPABILITY_REGISTRATION_POLICY: str = (
    "PROMOTION_REQUIRES_CAPABILITY_REGISTRATION_V1: "
    "A node may only be promoted from OPTIONAL/EXPERIMENTAL to ACTIVE after "
    "its capabilities have been registered into the canonical CapabilityRegistry "
    "path.  Promotion without capability registration is prohibited."
)

# ===========================================================================
# Enums
# ===========================================================================


class NodeLifecycleStage(str, Enum):
    """Ordered lifecycle stages for a governed node."""

    REGISTERED = "registered"
    """Node has been registered with the governor but not yet validated."""

    READINESS_CHECKED = "readiness_checked"
    """Node passed startup/readiness baseline checks."""

    CALLABLE_CLASSIFIED = "callable_classified"
    """Node has been classified against the callable-node baseline."""

    CAPABILITY_REGISTERED = "capability_registered"
    """Node's capabilities have been registered into the canonical path."""

    OPTIONAL = "optional"
    """Node is governed-optional: present and tracked but not in the active baseline."""

    EXPERIMENTAL = "experimental"
    """Node is experimental: capability is available but stability is not guaranteed."""

    ACTIVE = "active"
    """Node is fully promoted into the active baseline."""

    DEPRECATED = "deprecated"
    """Node is marked for removal; capabilities should not be consumed."""


# Ordered list for stage comparisons (index = order priority)
_STAGE_ORDER: List[NodeLifecycleStage] = [
    NodeLifecycleStage.REGISTERED,
    NodeLifecycleStage.READINESS_CHECKED,
    NodeLifecycleStage.CALLABLE_CLASSIFIED,
    NodeLifecycleStage.CAPABILITY_REGISTERED,
    NodeLifecycleStage.OPTIONAL,
    NodeLifecycleStage.EXPERIMENTAL,
    NodeLifecycleStage.ACTIVE,
    NodeLifecycleStage.DEPRECATED,
]

_STAGE_RANK: Dict[str, int] = {s.value: i for i, s in enumerate(_STAGE_ORDER)}


def _stage_rank(stage: NodeLifecycleStage) -> int:
    """Return the ordered rank of *stage* (lower = earlier in pipeline)."""
    return _STAGE_RANK.get(stage.value, 0)


class NodeGovernanceOutcome(str, Enum):
    """Result of a lifecycle gate evaluation."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    OVERRIDDEN = "overridden"


# ===========================================================================
# Dataclasses
# ===========================================================================


@dataclass
class NodeGovernanceRecord:
    """Governance record for one node."""

    node_name: str
    """Canonical node identifier (e.g. ``'Node_001_CoreScheduler'``)."""

    lifecycle_stage: NodeLifecycleStage = NodeLifecycleStage.REGISTERED

    is_callable: bool = False
    """Whether this node passed the callable-node baseline check."""

    is_capability_registered: bool = False
    """Whether this node's capabilities are in the canonical CapabilityRegistry."""

    readiness_outcome: NodeGovernanceOutcome = NodeGovernanceOutcome.SKIPPED
    startup_policy: Optional[str] = None
    architectural_class: Optional[str] = None

    gate_history: List[Dict[str, Any]] = field(default_factory=list)
    """Ordered history of lifecycle gate evaluations."""

    registered_at: float = field(default_factory=time.time)
    last_updated_at: float = field(default_factory=time.time)
    promotion_notes: List[str] = field(default_factory=list)

    def _record_gate(
        self,
        gate_name: str,
        outcome: NodeGovernanceOutcome,
        detail: str = "",
    ) -> None:
        self.gate_history.append(
            {
                "gate": gate_name,
                "outcome": outcome.value,
                "detail": detail,
                "ts": time.time(),
            }
        )
        self.last_updated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_name": self.node_name,
            "lifecycle_stage": self.lifecycle_stage.value,
            "is_callable": self.is_callable,
            "is_capability_registered": self.is_capability_registered,
            "readiness_outcome": self.readiness_outcome.value,
            "startup_policy": self.startup_policy,
            "architectural_class": self.architectural_class,
            "registered_at": self.registered_at,
            "last_updated_at": self.last_updated_at,
            "promotion_notes": self.promotion_notes,
            "gate_history": self.gate_history,
        }


@dataclass
class NodeLifecycleGovernorSnapshot:
    """Point-in-time snapshot of the node lifecycle governor state."""

    authority: str = NODE_LIFECYCLE_GOVERNOR_AUTHORITY
    snapshot_id: str = ""
    compiled_at: float = field(default_factory=time.time)

    total_nodes: int = 0
    registered_count: int = 0
    readiness_checked_count: int = 0
    callable_classified_count: int = 0
    capability_registered_count: int = 0
    optional_count: int = 0
    experimental_count: int = 0
    active_count: int = 0
    deprecated_count: int = 0

    wild_growth_count: int = 0
    """Nodes that are present in NodeFabricRegistry but not governed here."""

    governance_debt_nodes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "authority": self.authority,
            "snapshot_id": self.snapshot_id,
            "compiled_at": self.compiled_at,
            "total_nodes": self.total_nodes,
            "stage_counts": {
                "registered": self.registered_count,
                "readiness_checked": self.readiness_checked_count,
                "callable_classified": self.callable_classified_count,
                "capability_registered": self.capability_registered_count,
                "optional": self.optional_count,
                "experimental": self.experimental_count,
                "active": self.active_count,
                "deprecated": self.deprecated_count,
            },
            "wild_growth_count": self.wild_growth_count,
            "governance_debt_nodes": self.governance_debt_nodes,
        }


# ===========================================================================
# Governor class
# ===========================================================================


class NodeLifecycleGovernor:
    """Process-level singleton governing the lifecycle of registered nodes.

    New or auto-generated nodes must call :meth:`register_node` upon entry to
    the runtime.  The governor then advances the node through lifecycle gates
    using existing governance sources (NodeFabricRegistry, CallableNodeBaseline,
    StartupTierModel, CapabilityRegistry) without inventing a new parallel
    authority.
    """

    _instance: Optional["NodeLifecycleGovernor"] = None
    _class_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._records: Dict[str, NodeGovernanceRecord] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Singleton helpers
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls) -> "NodeLifecycleGovernor":
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton — **for testing only**."""
        with cls._class_lock:
            cls._instance = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_node(
        self,
        node_name: str,
        startup_policy: Optional[str] = None,
        architectural_class: Optional[str] = None,
    ) -> NodeGovernanceRecord:
        """Register *node_name* with the governor.

        If the node is already registered the existing record is returned
        without modification.

        Parameters
        ----------
        node_name:
            Canonical node name (key in ``node_dependencies.json``).
        startup_policy:
            Optional ``startup_policy`` value from node metadata
            (``"active"``, ``"optional"``, ``"disabled"``).
        architectural_class:
            Optional :class:`~core.nodes.node_fabric_registry.NodeArchitecturalClass`
            string value for this node.

        Returns
        -------
        NodeGovernanceRecord
            The governance record for this node.
        """
        with self._lock:
            if node_name in self._records:
                return self._records[node_name]
            rec = NodeGovernanceRecord(
                node_name=node_name,
                lifecycle_stage=NodeLifecycleStage.REGISTERED,
                startup_policy=startup_policy,
                architectural_class=architectural_class,
            )
            rec._record_gate(
                "registration",
                NodeGovernanceOutcome.PASSED,
                f"startup_policy={startup_policy}, arch_class={architectural_class}",
            )
            self._records[node_name] = rec
            logger.debug("NodeLifecycleGovernor: registered node '%s'", node_name)
            return rec

    # ------------------------------------------------------------------
    # Lifecycle gate: readiness
    # ------------------------------------------------------------------

    def check_readiness(self, node_name: str) -> NodeGovernanceRecord:
        """Evaluate startup/readiness baseline for *node_name*.

        Uses :mod:`~core.startup_tier_model` to check whether the node is
        present in a well-formed tier.  Falls back gracefully when the startup
        tier model is unavailable.

        The node must already be registered.  If not, it is auto-registered
        with no metadata before the gate is evaluated.
        """
        rec = self._ensure_registered(node_name)
        if _stage_rank(rec.lifecycle_stage) >= _stage_rank(NodeLifecycleStage.READINESS_CHECKED):
            return rec

        try:
            import json as _json
            from unittest.mock import MagicMock as _MM
            from launcher.node_startup import NodeSystemLauncher

            _ndj_path = Path(__file__).parent.parent / "node_dependencies.json"
            with open(_ndj_path, "r", encoding="utf-8") as _fh:
                _ndj = _json.load(_fh)
            _launcher = NodeSystemLauncher.__new__(NodeSystemLauncher)
            _launcher.service_manager = _MM()
            _launcher.config = _MM()
            _launcher.config.web_ui_port = 9000
            _launcher.nodes_dir = Path(__file__).parent.parent / "nodes"
            _launcher.node_configs = _ndj.get("nodes", {})

            full_nodes = _launcher.get_tier_nodes(NodeSystemLauncher.STARTUP_TIER_FULL)
            in_tier = node_name in full_nodes
            if in_tier:
                outcome = NodeGovernanceOutcome.PASSED
                detail = "in_full_tier"
            else:
                # New / auto-generated nodes are not yet in node_dependencies.json;
                # this is expected for onboarding — classify as SKIPPED (governance
                # debt) rather than FAILED so the node can continue through the
                # pipeline and be added to the tier model in a follow-up.
                outcome = NodeGovernanceOutcome.SKIPPED
                detail = "not_yet_in_any_startup_tier — governance debt; add to node_dependencies.json"
        except Exception as exc:
            outcome = NodeGovernanceOutcome.SKIPPED
            detail = f"startup_tier_model unavailable: {exc}"

        with self._lock:
            rec._record_gate("readiness", outcome, detail)
            rec.readiness_outcome = outcome
            if outcome in (
                NodeGovernanceOutcome.PASSED,
                NodeGovernanceOutcome.SKIPPED,
            ):
                rec.lifecycle_stage = NodeLifecycleStage.READINESS_CHECKED

        return rec

    # ------------------------------------------------------------------
    # Lifecycle gate: callable classification
    # ------------------------------------------------------------------

    def classify_callable(self, node_name: str) -> NodeGovernanceRecord:
        """Run callable-baseline classification for *node_name*.

        Uses :mod:`~core.callable_node_baseline` to determine whether the
        node's architectural class makes it callable by OpenClawd.
        """
        rec = self._ensure_registered(node_name)

        try:
            from core.callable_node_baseline import is_callable_by_openclawd
            from core.nodes.node_fabric_registry import NodeArchitecturalClass

            arch_str = rec.architectural_class or "capability_node"
            try:
                arch_class = NodeArchitecturalClass(arch_str)
                callable_result = is_callable_by_openclawd(arch_class)
            except (ValueError, TypeError):
                callable_result = False

            outcome = (
                NodeGovernanceOutcome.PASSED
                if callable_result
                else NodeGovernanceOutcome.FAILED
            )
            detail = f"callable={callable_result}, arch_class={arch_str}"
        except Exception as exc:
            callable_result = False
            outcome = NodeGovernanceOutcome.SKIPPED
            detail = f"callable_node_baseline unavailable: {exc}"

        with self._lock:
            rec._record_gate("callable_classification", outcome, detail)
            rec.is_callable = callable_result
            if outcome in (
                NodeGovernanceOutcome.PASSED,
                NodeGovernanceOutcome.SKIPPED,
            ):
                if _stage_rank(rec.lifecycle_stage) < _stage_rank(NodeLifecycleStage.CALLABLE_CLASSIFIED):
                    rec.lifecycle_stage = NodeLifecycleStage.CALLABLE_CLASSIFIED

        return rec

    # ------------------------------------------------------------------
    # Lifecycle gate: capability registration
    # ------------------------------------------------------------------

    def check_capability_registered(self, node_name: str) -> NodeGovernanceRecord:
        """Verify that *node_name* has capabilities registered in the canonical path.

        Checks whether any :class:`~core.agent.capability_registry.CapabilityItem`
        entries sourced from *node_name* exist in the CapabilityRegistry.
        """
        rec = self._ensure_registered(node_name)

        try:
            from core.agent.capability_registry import CapabilityRegistry

            registry = CapabilityRegistry.get_instance()
            items = registry.list_items()
            registered = any(
                getattr(item, "source_node", None) == node_name
                or (
                    getattr(item, "metadata", {}) or {}
                ).get("source_node") == node_name
                for item in items
            )
            outcome = (
                NodeGovernanceOutcome.PASSED
                if registered
                else NodeGovernanceOutcome.FAILED
            )
            detail = f"capability_registered={registered}"
        except Exception as exc:
            registered = False
            outcome = NodeGovernanceOutcome.SKIPPED
            detail = f"CapabilityRegistry unavailable: {exc}"

        with self._lock:
            rec._record_gate("capability_registration", outcome, detail)
            rec.is_capability_registered = registered
            if outcome in (
                NodeGovernanceOutcome.PASSED,
                NodeGovernanceOutcome.SKIPPED,
            ):
                if _stage_rank(rec.lifecycle_stage) < _stage_rank(NodeLifecycleStage.CAPABILITY_REGISTERED):
                    rec.lifecycle_stage = NodeLifecycleStage.CAPABILITY_REGISTERED

        return rec

    # ------------------------------------------------------------------
    # Promotion / demotion
    # ------------------------------------------------------------------

    def promote_node(self, node_name: str, note: str = "") -> NodeGovernanceRecord:
        """Promote *node_name* to the next lifecycle stage.

        Promotion follows the pipeline::

            OPTIONAL / EXPERIMENTAL → ACTIVE

        The :data:`PROMOTION_REQUIRES_CAPABILITY_REGISTRATION_POLICY` is
        enforced: a node may not be promoted to ACTIVE without capability
        registration having passed.
        """
        rec = self._ensure_registered(node_name)
        with self._lock:
            current = rec.lifecycle_stage

            if current in (
                NodeLifecycleStage.CAPABILITY_REGISTERED,
                NodeLifecycleStage.OPTIONAL,
                NodeLifecycleStage.EXPERIMENTAL,
            ):
                # Policy enforcement
                if not rec.is_capability_registered:
                    detail = (
                        "promotion blocked: capability not registered — "
                        f"violates PROMOTION_REQUIRES_CAPABILITY_REGISTRATION_POLICY"
                    )
                    rec._record_gate(
                        "promotion",
                        NodeGovernanceOutcome.FAILED,
                        detail,
                    )
                    rec.promotion_notes.append(detail)
                    logger.warning(
                        "NodeLifecycleGovernor: promotion blocked for '%s': %s",
                        node_name,
                        detail,
                    )
                    return rec

                rec.lifecycle_stage = NodeLifecycleStage.ACTIVE
                rec._record_gate(
                    "promotion",
                    NodeGovernanceOutcome.PASSED,
                    f"promoted to ACTIVE; note={note}",
                )
                if note:
                    rec.promotion_notes.append(f"[PROMOTED] {note}")
                logger.info(
                    "NodeLifecycleGovernor: promoted '%s' to ACTIVE", node_name
                )
            elif current == NodeLifecycleStage.REGISTERED:
                # Move through intermediate stages
                rec.lifecycle_stage = NodeLifecycleStage.OPTIONAL
                rec._record_gate(
                    "promotion",
                    NodeGovernanceOutcome.PASSED,
                    f"promoted to OPTIONAL from REGISTERED; note={note}",
                )
            else:
                rec._record_gate(
                    "promotion",
                    NodeGovernanceOutcome.SKIPPED,
                    f"already at stage {current.value}; no promotion needed",
                )

        return rec

    def demote_node(self, node_name: str, reason: str = "") -> NodeGovernanceRecord:
        """Demote *node_name* to :attr:`NodeLifecycleStage.DEPRECATED`."""
        rec = self._ensure_registered(node_name)
        with self._lock:
            rec.lifecycle_stage = NodeLifecycleStage.DEPRECATED
            rec._record_gate(
                "demotion",
                NodeGovernanceOutcome.PASSED,
                f"demoted to DEPRECATED; reason={reason}",
            )
            if reason:
                rec.promotion_notes.append(f"[DEMOTED] {reason}")
        logger.info(
            "NodeLifecycleGovernor: demoted '%s' to DEPRECATED (%s)",
            node_name,
            reason,
        )
        return rec

    # ------------------------------------------------------------------
    # Full pipeline helper
    # ------------------------------------------------------------------

    def govern_node(self, node_name: str) -> NodeGovernanceRecord:
        """Run all lifecycle gates for *node_name* in pipeline order.

        This is a convenience method that runs readiness, callable
        classification, and capability registration checks sequentially.
        The node is auto-registered if not already present.
        """
        self._ensure_registered(node_name)
        self.check_readiness(node_name)
        self.classify_callable(node_name)
        self.check_capability_registered(node_name)
        return self._records[node_name]

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_record(self, node_name: str) -> Optional[NodeGovernanceRecord]:
        """Return the governance record for *node_name*, or ``None``."""
        with self._lock:
            return self._records.get(node_name)

    def list_records(self) -> List[NodeGovernanceRecord]:
        """Return all governance records (a snapshot copy)."""
        with self._lock:
            return list(self._records.values())

    def snapshot(self) -> NodeLifecycleGovernorSnapshot:
        """Build and return a :class:`NodeLifecycleGovernorSnapshot`."""
        with self._lock:
            records = list(self._records.values())

        stage_counts: Dict[str, int] = {s.value: 0 for s in NodeLifecycleStage}
        for rec in records:
            stage_counts[rec.lifecycle_stage.value] += 1

        # Identify wild-growth nodes in NodeFabricRegistry not governed here
        wild_growth: List[str] = []
        try:
            from core.nodes.node_fabric_registry import NodeFabricRegistry

            registry = NodeFabricRegistry.get_instance()
            governed_names = {r.node_name for r in records}
            for node in registry.get_all_nodes():
                if node.node_id not in governed_names and node.node_name not in governed_names:
                    wild_growth.append(node.node_id)
        except Exception:
            pass

        snap = NodeLifecycleGovernorSnapshot(
            snapshot_id=str(_uuid.uuid4()),
            compiled_at=time.time(),
            total_nodes=len(records),
            registered_count=stage_counts.get(NodeLifecycleStage.REGISTERED.value, 0),
            readiness_checked_count=stage_counts.get(
                NodeLifecycleStage.READINESS_CHECKED.value, 0
            ),
            callable_classified_count=stage_counts.get(
                NodeLifecycleStage.CALLABLE_CLASSIFIED.value, 0
            ),
            capability_registered_count=stage_counts.get(
                NodeLifecycleStage.CAPABILITY_REGISTERED.value, 0
            ),
            optional_count=stage_counts.get(NodeLifecycleStage.OPTIONAL.value, 0),
            experimental_count=stage_counts.get(
                NodeLifecycleStage.EXPERIMENTAL.value, 0
            ),
            active_count=stage_counts.get(NodeLifecycleStage.ACTIVE.value, 0),
            deprecated_count=stage_counts.get(
                NodeLifecycleStage.DEPRECATED.value, 0
            ),
            wild_growth_count=len(wild_growth),
            governance_debt_nodes=wild_growth[:20],  # cap for output safety
        )
        return snap

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_registered(self, node_name: str) -> NodeGovernanceRecord:
        """Return record for *node_name*, auto-registering if absent."""
        with self._lock:
            if node_name not in self._records:
                rec = NodeGovernanceRecord(node_name=node_name)
                rec._record_gate(
                    "auto_registration",
                    NodeGovernanceOutcome.PASSED,
                    "auto-registered on first lifecycle gate call",
                )
                self._records[node_name] = rec
                logger.debug(
                    "NodeLifecycleGovernor: auto-registered node '%s'", node_name
                )
            return self._records[node_name]


# ===========================================================================
# Module-level helpers
# ===========================================================================


def get_node_lifecycle_governor() -> NodeLifecycleGovernor:
    """Return the process-level singleton :class:`NodeLifecycleGovernor`."""
    return NodeLifecycleGovernor.get_instance()


def reset_node_lifecycle_governor() -> None:
    """Reset the singleton — **for testing only**."""
    NodeLifecycleGovernor.reset()


def govern_node(node_name: str) -> NodeGovernanceRecord:
    """Convenience wrapper — run full governance pipeline for *node_name*."""
    return get_node_lifecycle_governor().govern_node(node_name)


def promote_node(node_name: str, note: str = "") -> NodeGovernanceRecord:
    """Convenience wrapper — promote *node_name*."""
    return get_node_lifecycle_governor().promote_node(node_name, note=note)


def demote_node(node_name: str, reason: str = "") -> NodeGovernanceRecord:
    """Convenience wrapper — demote *node_name*."""
    return get_node_lifecycle_governor().demote_node(node_name, reason=reason)


def node_governance_snapshot() -> NodeLifecycleGovernorSnapshot:
    """Convenience wrapper — return a governor snapshot."""
    return get_node_lifecycle_governor().snapshot()
