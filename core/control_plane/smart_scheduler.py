#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy Control Plane — Smart Scheduler
========================================

PR-8: Orchestration Decision-Support Tool
------------------------------------------
:class:`DeviceScoringEngine` is an **orchestration decision-support** component.
It operates within the orchestration layer (not the substrate) and is called by
:class:`~core.swarm_coordinator.SwarmCoordinator` during the planning phase —
*before* any substrate dispatch occurs.

Architectural role
~~~~~~~~~~~~~~~~~~
* **Orchestration layer** (SwarmCoordinator, DeviceScoringEngine) — answers
  the question: *"which device should handle this agent/task, and why?"*
* **Substrate layer** (CommandRouter, route_envelope) — answers the question:
  *"how do I transport this command/envelope to the selected device?"*

``DeviceScoringEngine`` never calls into the substrate.  It only produces
:class:`DeviceScore` objects that the orchestration layer uses to make
device-assignment decisions.

Provides a deterministic, heuristic-based device scoring and selection
engine used by the Control Plane to route tasks to the most suitable
device or agent executor.

Scoring formula
---------------
The composite score for a device is:

    S = w_cap  * capability_score(required, available)
      + w_ping * latency_score(ping_latency_ms)
      + w_load * load_score(load_pct)
      + w_sb   * sandbox_score(sandbox_level)

All component scores are normalised to [0, 1] before weighting.
Higher is better.

Component definitions
---------------------
* **capability_score** – Jaccard-like: ``|required ∩ available| / |required|``
  (1.0 when the device has every required capability).
* **latency_score**   – ``max(0, 1 − ping_ms / latency_ceiling_ms)``.
  Zero when ``ping_ms`` exceeds the ceiling (default 2 000 ms).
* **load_score**      – ``1 − (load_pct / 100)``.  Full score at zero load.
* **sandbox_score**   – Normalised from the :class:`SandboxLevel` ordinal.
  Higher sandbox level → lower score (more locked-down device is less
  preferred for general tasks; callers may invert this for security-first
  routing by adjusting ``w_sb``).

Usage
-----
    from core.control_plane.smart_scheduler import (
        DeviceScoreInput,
        CapabilityDescriptor,
        DeviceScoringEngine,
        ScoringWeights,
    )

    engine = DeviceScoringEngine()
    score = engine.score_device(
        DeviceScoreInput(
            device_id="dev_01",
            ping_latency_ms=80.0,
            load_pct=30.0,
            sandbox_level=SandboxLevel.STANDARD,
            capabilities=["screen", "keyboard", "touch"],
        ),
        required_capabilities=["screen", "keyboard"],
    )
    print(score.total)   # e.g. 0.87
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any, Dict, List, Optional, Sequence

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class SandboxLevel(IntEnum):
    """Device sandbox / trust level.

    Higher ordinal = more restrictive / lower trust.
    Scores are inverted: NONE (0) has the highest sandbox score contribution.
    """

    NONE = 0        # bare-metal or fully trusted host
    BASIC = 1       # minimal process isolation
    STANDARD = 2    # standard OS sandbox (e.g. Android work profile)
    STRICT = 3      # strict policy (SELinux enforcing, restricted APIs)
    MAXIMUM = 4     # locked-down kiosk / air-gapped device


class DeviceStatus(str):
    """Predefined device availability status strings."""

    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    DRAINING = "draining"    # accepting no new work
    MAINTENANCE = "maintenance"
    QUARANTINED = "quarantined"  # excluded from scheduling until manually reset
    CIRCUIT_OPEN = "circuit_open"  # circuit breaker tripped


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CapabilityDescriptor(BaseModel):
    """Describes a single device capability with optional metadata."""

    name: str = Field(..., description="Unique capability name, e.g. 'screen', 'touch'.")
    version: Optional[str] = Field(None, description="Capability version string, if applicable.")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extra metadata (resolution, locale, etc.).",
    )


class ScoringWeights(BaseModel):
    """Configurable weight vector for the scoring formula.

    All weights must be non-negative.  They are **not** automatically
    normalised — callers choose magnitudes to express relative priority.
    """

    capability: float = Field(default=0.35, ge=0.0, description="Weight for capability match.")
    latency: float = Field(default=0.22, ge=0.0, description="Weight for ping latency score.")
    load: float = Field(default=0.22, ge=0.0, description="Weight for device load score.")
    sandbox: float = Field(default=0.09, ge=0.0, description="Weight for sandbox level score.")
    health: float = Field(default=0.12, ge=0.0, description="Weight for composite device health score.")

    @model_validator(mode="after")
    def _at_least_one_nonzero(self) -> "ScoringWeights":
        if self.capability + self.latency + self.load + self.sandbox + self.health == 0:
            raise ValueError("At least one weight must be non-zero.")
        return self


class DeviceScoreInput(BaseModel):
    """All observable metrics required to score a single device candidate."""

    device_id: str = Field(..., description="Unique device identifier.")
    status: str = Field(
        default=DeviceStatus.ONLINE,
        description="Current device availability status.",
    )
    ping_latency_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Round-trip ping latency to this device in milliseconds.",
    )
    load_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Current CPU/task load as a percentage [0, 100].",
    )
    sandbox_level: SandboxLevel = Field(
        default=SandboxLevel.NONE,
        description="Device sandbox / trust level.",
    )
    capabilities: List[str] = Field(
        default_factory=list,
        description="List of capability names currently available on this device.",
    )
    health_score: float = Field(
        default=100.0,
        ge=0.0,
        le=100.0,
        description=(
            "Composite health score [0, 100] from the DeviceHealthRegistry "
            "(heartbeat latency + error rate + circuit-breaker penalties). "
            "Defaults to 100 (fully healthy) when health tracking is unavailable."
        ),
    )
    # PR-6: optional pre-computed execution profile for mode-aware scheduling.
    # When present this allows the scoring engine (and callers) to reason about
    # whether the device supports agent_runtime vs command_only without
    # re-deriving the profile inside the engine itself.
    execution_profile: Optional[Any] = Field(
        default=None,
        description=(
            "Optional DeviceExecutionProfile for this device. "
            "When set, callers can use it to filter or prefer devices by execution mode "
            "without modifying the scoring formula."
        ),
        exclude=True,  # excluded from serialisation to keep the wire format stable
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extra attributes for logging / debugging.",
    )


class DeviceScore(BaseModel):
    """Scoring result for a single device candidate."""

    device_id: str
    capability_score: float = Field(ge=0.0, le=1.0)
    latency_score: float = Field(ge=0.0, le=1.0)
    load_score: float = Field(ge=0.0, le=1.0)
    sandbox_score: float = Field(ge=0.0, le=1.0)
    health_score: float = Field(default=1.0, ge=0.0, le=1.0, description="Normalised health score [0, 1].")
    total: float = Field(ge=0.0, description="Weighted composite score (not normalised to 1).")
    eligible: bool = Field(
        default=True,
        description=(
            "False if the device was disqualified before scoring "
            "(offline, missing required capabilities with hard-match, etc.)."
        ),
    )
    disqualify_reason: Optional[str] = Field(None, description="Human-readable reason if ineligible.")


# ---------------------------------------------------------------------------
# Scoring engine
# ---------------------------------------------------------------------------

class DeviceScoringEngine:
    """Deterministic, heuristic-based device scoring engine.

    Parameters
    ----------
    weights:
        Scoring weight configuration.  Defaults to :class:`ScoringWeights`
        default values (cap=0.40, latency=0.25, load=0.25, sandbox=0.10).
    latency_ceiling_ms:
        Latency above which ``latency_score`` is 0.  Default 2 000 ms.
    require_all_capabilities:
        When ``True`` (default), devices that lack **any** required
        capability receive ``eligible=False`` and are never selected.
        Set to ``False`` to allow partial-match devices (ranked lower).
    """

    def __init__(
        self,
        weights: Optional[ScoringWeights] = None,
        latency_ceiling_ms: float = 2000.0,
        require_all_capabilities: bool = True,
    ) -> None:
        self.weights = weights or ScoringWeights()
        self.latency_ceiling_ms = max(latency_ceiling_ms, 1.0)
        self.require_all_capabilities = require_all_capabilities

    # ------------------------------------------------------------------
    # Component score helpers (all return float in [0, 1])
    # ------------------------------------------------------------------

    def _capability_score(
        self, required: Sequence[str], available: Sequence[str]
    ) -> float:
        """Fraction of required capabilities present on the device.

        Returns 1.0 when *required* is empty (no capability constraint).
        """
        if not required:
            return 1.0
        required_set = set(required)
        available_set = set(available)
        intersection = required_set & available_set
        return len(intersection) / len(required_set)

    def _latency_score(self, ping_ms: float) -> float:
        """Linear decay: 1.0 at 0 ms, 0.0 at ``latency_ceiling_ms``."""
        return max(0.0, 1.0 - ping_ms / self.latency_ceiling_ms)

    def _load_score(self, load_pct: float) -> float:
        """1.0 at 0% load, 0.0 at 100% load."""
        return 1.0 - load_pct / 100.0

    def _sandbox_score(self, level: SandboxLevel) -> float:
        """Inverse of sandbox level: NONE→1.0, MAXIMUM→0.0."""
        max_level = max(int(lvl) for lvl in SandboxLevel)
        if max_level == 0:
            return 1.0
        return 1.0 - int(level) / max_level

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score_device(
        self,
        device: DeviceScoreInput,
        required_capabilities: Optional[List[str]] = None,
    ) -> DeviceScore:
        """Score a single device against an optional capability requirement.

        Parameters
        ----------
        device:
            Observed metrics for the candidate device.
        required_capabilities:
            Capabilities that must (or should) be present.  ``None`` / empty
            means no capability constraint.

        Returns
        -------
        DeviceScore
            Component scores and weighted total.
        """
        required = required_capabilities or []

        # Hard eligibility checks
        if device.status in (
            DeviceStatus.OFFLINE,
            DeviceStatus.MAINTENANCE,
            DeviceStatus.QUARANTINED,
            DeviceStatus.CIRCUIT_OPEN,
        ):
            return DeviceScore(
                device_id=device.device_id,
                capability_score=0.0,
                latency_score=0.0,
                load_score=0.0,
                sandbox_score=0.0,
                health_score=0.0,
                total=0.0,
                eligible=False,
                disqualify_reason=f"Device status is '{device.status}'.",
            )

        cap_score = self._capability_score(required, device.capabilities)

        if self.require_all_capabilities and cap_score < 1.0:
            return DeviceScore(
                device_id=device.device_id,
                capability_score=cap_score,
                latency_score=0.0,
                load_score=0.0,
                sandbox_score=0.0,
                health_score=0.0,
                total=0.0,
                eligible=False,
                disqualify_reason=(
                    f"Missing required capabilities: "
                    f"{sorted(set(required) - set(device.capabilities))}"
                ),
            )

        lat_score = self._latency_score(device.ping_latency_ms)
        load_score = self._load_score(device.load_pct)
        sb_score = self._sandbox_score(device.sandbox_level)
        # Normalise health_score from [0, 100] to [0, 1]
        hlth_score = max(0.0, min(1.0, device.health_score / 100.0))

        w = self.weights
        total = (
            w.capability * cap_score
            + w.latency * lat_score
            + w.load * load_score
            + w.sandbox * sb_score
            + w.health * hlth_score
        )

        return DeviceScore(
            device_id=device.device_id,
            capability_score=cap_score,
            latency_score=lat_score,
            load_score=load_score,
            sandbox_score=sb_score,
            health_score=hlth_score,
            total=total,
        )

    def select_best_device(
        self,
        candidates: List[DeviceScoreInput],
        required_capabilities: Optional[List[str]] = None,
    ) -> Optional[DeviceScore]:
        """Score all *candidates* and return the one with the highest total.

        Returns ``None`` if the list is empty or no candidate is eligible.

        Parameters
        ----------
        candidates:
            Observed metrics for all candidate devices.
        required_capabilities:
            Capability requirements forwarded to :meth:`score_device`.
        """
        if not candidates:
            return None

        scores = [
            self.score_device(d, required_capabilities) for d in candidates
        ]
        eligible = [s for s in scores if s.eligible]
        if not eligible:
            return None

        # Deterministic tie-break: device_id lexicographic order
        return max(eligible, key=lambda s: (s.total, s.device_id))

    def rank_devices(
        self,
        candidates: List[DeviceScoreInput],
        required_capabilities: Optional[List[str]] = None,
    ) -> List[DeviceScore]:
        """Return all eligible candidates ranked best-first.

        Ineligible devices are appended at the end (total=0) for
        diagnostic transparency.
        """
        scores = [
            self.score_device(d, required_capabilities) for d in candidates
        ]
        eligible = sorted(
            [s for s in scores if s.eligible],
            key=lambda s: (s.total, s.device_id),
            reverse=True,
        )
        ineligible = [s for s in scores if not s.eligible]
        return eligible + ineligible
