#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/unified/capability_contract.py
======================================
PR-002 — Canonical Capability Contract Schema (Promoted to Authoritative Schema)

**Canonical role**: ``CapabilityContract`` is the *required normalised
descriptor model* for every capability in the Galaxy system.  All capability
sources (``mcp_loader``, ``skill_loader``, device-registration paths, node
fabric registry) **must** produce a valid :class:`CapabilityContract` before a
capability can be registered in
:class:`~core.agent.capability_registry.CapabilityRegistry`.

Architecture contract
---------------------
- ``CapabilityContract`` = the single schema expectation across all capability
  sources (MCP, Skill, Device/Gateway, Node).
- :func:`validate_capability_contract` is the enforcement gate — it must be
  called at registration time.
- :class:`~core.unified.capability_resolver.CapabilityResolver` re-validates
  all contracts before returning them to consumers, ensuring that only
  well-formed entries reach ``OpenClawd`` or other scheduling paths.

Usage::

    from core.unified.capability_contract import (
        CapabilityContract,
        CapabilitySource,
        validate_capability_contract,
    )

    contract = CapabilityContract(
        name="take_screenshot",
        description="Capture the current screen state.",
        source=CapabilitySource.DEVICE,
        source_id="android_01",
        parameters={
            "type": "object",
            "properties": {
                "format": {"type": "string", "enum": ["png", "jpeg"]},
            },
        },
    )
    validate_capability_contract(contract)   # raises CapabilityContractError on schema errors
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.Unified.CapabilityContract")

# ---------------------------------------------------------------------------
# Batch PR-6: Capability contract authority sentinel
# ---------------------------------------------------------------------------

CAPABILITY_CONTRACT_AUTHORITY = "core.unified.capability_contract.CapabilityContract"
"""Sentinel: ``CapabilityContract`` is the canonical schema/validation layer
for all capability entries.

Responsibility (Batch PR-6 clarification)
-----------------------------------------
- **Role**: defines and validates the required shape of every capability
  before it can be registered in ``CapabilityRegistry``.
- Called at registration time by ``CapabilityRegistry.inject_*()`` methods.
- Re-validated by ``CapabilityResolver`` before entries are returned to
  consumers (e.g. ``OpenClawd``).
- **NOT** a registry, bus, runtime monitor, or orchestrator.
"""


class CapabilitySource(str, Enum):
    """Origin of a capability entry."""

    MCP = "mcp"
    """Provided by an MCP (Model Context Protocol) server tool."""

    SKILL = "skill"
    """Provided by a Galaxy Skill (SKILL.md or skill_loader)."""

    DEVICE = "device"
    """Provided by a registered device capability."""

    GATEWAY = "gateway"
    """Provided by the Galaxy Gateway plane."""

    NODE = "node"
    """Provided by a node in the node fabric registry."""

    UNKNOWN = "unknown"
    """Source could not be determined (legacy compat)."""


# ---------------------------------------------------------------------------
# CapabilityContract
# ---------------------------------------------------------------------------


@dataclass
class CapabilityContract:
    """Unified capability descriptor shared across all Galaxy subsystems.

    Attributes
    ----------
    name : str
        Unique capability identifier (snake_case recommended).
    description : str
        Human-readable description of what the capability does.
    source : CapabilitySource
        Origin of the capability.
    source_id : str
        Source-specific identifier (server_id, skill_id, device_id, …).
    version : str
        Semantic version of the capability definition (default ``"1.0.0"``).
    parameters : dict
        JSON Schema object describing the accepted parameters.
        Must be ``{"type": "object", "properties": {...}}`` or ``{}``.
    available : bool
        Whether the capability is currently accessible.
    tags : list[str]
        Optional taxonomy tags (e.g. ``["ui", "screen"]``).
    metadata : dict
        Arbitrary extension metadata for observability and routing hints.
    contract_id : str
        Auto-generated unique identifier for this contract instance.
    created_at : float
        Unix timestamp of contract creation.
    """

    name: str
    description: str
    source: CapabilitySource = CapabilitySource.UNKNOWN
    source_id: str = ""
    version: str = "1.0.0"
    parameters: Dict[str, Any] = field(default_factory=dict)
    available: bool = True
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    contract_id: str = field(default_factory=lambda: f"cap_{uuid.uuid4().hex[:12]}")
    created_at: float = field(default_factory=time.time)

    # ── Serialisation ────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "name": self.name,
            "description": self.description,
            "source": self.source.value if isinstance(self.source, CapabilitySource) else self.source,
            "source_id": self.source_id,
            "version": self.version,
            "parameters": dict(self.parameters),
            "available": self.available,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CapabilityContract":
        src_raw = data.get("source", "unknown")
        try:
            src = CapabilitySource(src_raw)
        except ValueError:
            src = CapabilitySource.UNKNOWN
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            source=src,
            source_id=data.get("source_id", ""),
            version=data.get("version", "1.0.0"),
            parameters=data.get("parameters", {}),
            available=bool(data.get("available", True)),
            tags=list(data.get("tags", [])),
            metadata=data.get("metadata", {}),
            contract_id=data.get("contract_id", f"cap_{uuid.uuid4().hex[:12]}"),
            created_at=float(data.get("created_at", time.time())),
        )

    def to_tool_schema(self) -> Dict[str, Any]:
        """Return OpenAI function-calling format schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {"type": "object", "properties": {}},
            },
        }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

REQUIRED_CONTRACT_FIELDS = ("name", "description")
"""Fields that MUST be non-empty for a capability contract to be valid."""


class CapabilityContractError(ValueError):
    """Raised when a :class:`CapabilityContract` fails validation.

    Attributes
    ----------
    violations : list[str]
        Human-readable descriptions of each schema violation.
    error_code : str
        Machine-readable error code.
    """

    error_code = "CAPABILITY_CONTRACT_INVALID"

    def __init__(self, violations: List[str], name: str = "") -> None:
        self.violations = violations
        self.capability_name = name
        super().__init__(
            f"CapabilityContract '{name}' invalid: {violations}"
        )


def validate_capability_contract(contract: CapabilityContract) -> None:
    """Validate *contract* and raise :class:`CapabilityContractError` on failure.

    Checks
    ------
    1. Required fields are non-empty.
    2. *parameters* is either empty or a valid JSON Schema object
       (must be a dict; ``type`` field when present must be a string).
    3. *source* is a known :class:`CapabilitySource` value.
    """
    violations: List[str] = []

    # 1. Required fields
    for fname in REQUIRED_CONTRACT_FIELDS:
        if not getattr(contract, fname, ""):
            violations.append(f"'{fname}' is required and must not be empty")

    # 2. Parameters schema validation
    params = contract.parameters
    if params:
        if not isinstance(params, dict):
            violations.append(
                f"'parameters' must be a dict (JSON Schema object), got {type(params).__name__}"
            )
        else:
            ptype = params.get("type")
            if ptype is not None and not isinstance(ptype, str):
                violations.append(
                    "'parameters.type' must be a string when present"
                )
            props = params.get("properties")
            if props is not None and not isinstance(props, dict):
                violations.append(
                    "'parameters.properties' must be a dict when present"
                )

    # 3. Source enum
    if isinstance(contract.source, str):
        try:
            CapabilitySource(contract.source)
        except ValueError:
            violations.append(
                f"'source' value '{contract.source}' is not a valid CapabilitySource"
            )

    if violations:
        logger.warning(
            "CapabilityContract validation failed for '%s': %s",
            contract.name,
            violations,
            extra={
                "event": "capability_contract_invalid",
                "capability_name": contract.name,
                "violations": violations,
                "error_code": CapabilityContractError.error_code,
            },
        )
        raise CapabilityContractError(violations, contract.name)

    logger.debug(
        "CapabilityContract validated: %s (source=%s)",
        contract.name,
        contract.source,
        extra={
            "event": "capability_contract_validated",
            "capability_name": contract.name,
            "source": str(contract.source),
            "contract_id": contract.contract_id,
        },
    )


def is_valid_capability_contract(contract: CapabilityContract) -> bool:
    """Return ``True`` iff *contract* passes validation (no exception raised)."""
    try:
        validate_capability_contract(contract)
        return True
    except CapabilityContractError:
        return False
