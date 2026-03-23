"""
core/mcp_addon_contract.py
===========================
PR-004 — Canonical MCP Addon Contract

Defines the **authoritative schema** for ``mcp_tool.json`` manifests that ship
inside GitHub-installable MCP addon repositories.

Any compliant addon repo must include a ``mcp_tool.json`` at its root.
``GitHubInstaller`` reads this file and passes it through
:func:`validate_mcp_addon_contract` before loading the MCP server; invalid
addons are rejected with structured :class:`MCPAddonContractError` errors.

Schema (``schema_version`` = ``"1"``)
--------------------------------------
Required fields:

``name`` (str)
    Unique identifier for this addon.  Must match ``[A-Za-z0-9_-]+``.

``entrypoint`` (str or list[str])
    How to launch the MCP server process.  Examples::

        "entrypoint": "server.py"                   # Python file — python is prepended
        "entrypoint": ["node", "dist/server.js"]    # explicit command list

Optional fields:

``schema_version`` (str, default ``"1"``)
    Contract schema version.  Must be ``"1"`` for the current release.
    Future schema revisions will bump this value.

``description`` (str)
    Human-readable description of what this addon provides.

``protocol`` (str, default ``"mcp"``)
    Communication protocol.  Only ``"mcp"`` is supported.

``transport`` (str, default ``"stdio"``)
    Transport layer.  Only ``"stdio"`` is supported.

``dependencies`` (list[str])
    Pip package specifiers to install before launching the server.

``env`` (dict[str, str])
    Environment variables to inject into the server process.

``capabilities`` (dict)
    Optional metadata describing the capabilities provided (for documentation
    and capability-catalog hints; not machine-enforced beyond type check).

``repository`` (str)
    Source repository URL (informational).

``author`` (str)
    Maintainer name or email (informational).

``version`` (str)
    Addon release version, e.g. ``"1.2.3"`` (informational; not the same as
    ``schema_version``).

Validation
----------
:func:`validate_mcp_addon_contract` raises :class:`MCPAddonContractError` on
any violation.  Each violation is listed in ``exc.violations``.

Usage::

    from core.mcp_addon_contract import validate_mcp_addon_contract, MCPAddonContractError

    try:
        contract = validate_mcp_addon_contract(raw_manifest)
    except MCPAddonContractError as exc:
        print("Invalid addon:", exc.violations)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("Galaxy.MCPAddonContract")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The current (and only) supported schema version string.
CURRENT_SCHEMA_VERSION = "1"

#: Supported protocol value.
SUPPORTED_PROTOCOL = "mcp"

#: Supported transport values.
SUPPORTED_TRANSPORTS = {"stdio"}

#: Regex for valid addon names.
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------


class MCPAddonContractError(ValueError):
    """Raised when an ``mcp_tool.json`` manifest fails contract validation.

    Attributes
    ----------
    violations : list[str]
        Human-readable description of each schema violation.
    error_code : str
        Machine-readable error code ``"MCP_ADDON_CONTRACT_INVALID"``.
    """

    error_code = "MCP_ADDON_CONTRACT_INVALID"

    def __init__(self, violations: List[str], name: str = "") -> None:
        self.violations = list(violations)
        self.addon_name = name
        msg = f"MCPAddonContract '{name}' invalid: {violations}"
        super().__init__(msg)


# ---------------------------------------------------------------------------
# Contract dataclass
# ---------------------------------------------------------------------------


@dataclass
class MCPAddonContract:
    """Validated, normalised representation of a ``mcp_tool.json`` manifest.

    Do **not** construct directly; use :func:`validate_mcp_addon_contract`
    which validates the raw dict and returns a populated instance.
    """

    # Required
    name: str
    entrypoint: Union[str, List[str]]

    # Optional with defaults
    schema_version: str = CURRENT_SCHEMA_VERSION
    description: str = ""
    protocol: str = SUPPORTED_PROTOCOL
    transport: str = "stdio"
    dependencies: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)

    # Informational / capability metadata
    capabilities: Dict[str, Any] = field(default_factory=dict)
    repository: str = ""
    author: str = ""
    version: str = ""

    # ── Serialisation ────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "entrypoint": self.entrypoint,
            "description": self.description,
            "protocol": self.protocol,
            "transport": self.transport,
            "dependencies": self.dependencies,
            "env": self.env,
            "capabilities": self.capabilities,
            "repository": self.repository,
            "author": self.author,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPAddonContract":
        """Construct without validation (internal use only)."""
        return cls(
            name=data.get("name", ""),
            entrypoint=data.get("entrypoint", ""),
            schema_version=str(data.get("schema_version", CURRENT_SCHEMA_VERSION)),
            description=str(data.get("description", "")),
            protocol=str(data.get("protocol", SUPPORTED_PROTOCOL)),
            transport=str(data.get("transport", "stdio")),
            dependencies=list(data.get("dependencies") or []),
            env=dict(data.get("env") or {}),
            capabilities=dict(data.get("capabilities") or {}),
            repository=str(data.get("repository", "")),
            author=str(data.get("author", "")),
            version=str(data.get("version", "")),
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_mcp_addon_contract(
    raw: Dict[str, Any],
    *,
    allow_future_schema: bool = False,
) -> MCPAddonContract:
    """Validate *raw* manifest dict and return a :class:`MCPAddonContract`.

    Parameters
    ----------
    raw:
        Parsed content of ``mcp_tool.json``.
    allow_future_schema:
        If ``True``, schema versions newer than :data:`CURRENT_SCHEMA_VERSION`
        are accepted with a warning instead of raising an error.  Intended for
        forward-compatibility in test environments.

    Returns
    -------
    MCPAddonContract
        A fully validated and normalised contract instance.

    Raises
    ------
    MCPAddonContractError
        When one or more validation rules are violated.  All violations are
        collected before raising so callers see the complete list.
    TypeError
        When *raw* is not a dict.
    """
    if not isinstance(raw, dict):
        raise TypeError(
            f"mcp_tool.json must be a JSON object (dict), got {type(raw).__name__}"
        )

    violations: List[str] = []
    name: str = raw.get("name", "")

    # ── Required: name ────────────────────────────────────────────────────────
    if not name or not isinstance(name, str):
        violations.append("'name' is required and must be a non-empty string")
    elif not _NAME_RE.match(name):
        violations.append(
            f"'name' must match [A-Za-z0-9_-]+, got {name!r}"
        )

    # ── Required: entrypoint ─────────────────────────────────────────────────
    entrypoint = raw.get("entrypoint")
    if entrypoint is None:
        violations.append("'entrypoint' is required")
    elif isinstance(entrypoint, str):
        if not entrypoint.strip():
            violations.append("'entrypoint' must not be an empty string")
    elif isinstance(entrypoint, list):
        if not entrypoint:
            violations.append("'entrypoint' list must not be empty")
        elif not all(isinstance(part, str) for part in entrypoint):
            violations.append("'entrypoint' list entries must all be strings")
    else:
        violations.append(
            f"'entrypoint' must be a string or list of strings, got {type(entrypoint).__name__}"
        )

    # ── Optional: schema_version ─────────────────────────────────────────────
    schema_version = str(raw.get("schema_version", CURRENT_SCHEMA_VERSION))
    if schema_version != CURRENT_SCHEMA_VERSION:
        msg = (
            f"'schema_version' {schema_version!r} is not supported; "
            f"expected {CURRENT_SCHEMA_VERSION!r}"
        )
        if allow_future_schema:
            logger.warning("MCPAddonContract: %s (accepted via allow_future_schema)", msg)
        else:
            violations.append(msg)

    # ── Optional: protocol ───────────────────────────────────────────────────
    protocol = raw.get("protocol", SUPPORTED_PROTOCOL)
    if protocol is not None and protocol != SUPPORTED_PROTOCOL:
        violations.append(
            f"'protocol' must be {SUPPORTED_PROTOCOL!r}, got {protocol!r}"
        )

    # ── Optional: transport ──────────────────────────────────────────────────
    transport = raw.get("transport", "stdio")
    if transport is not None and transport not in SUPPORTED_TRANSPORTS:
        violations.append(
            f"'transport' must be one of {sorted(SUPPORTED_TRANSPORTS)}, got {transport!r}"
        )

    # ── Optional: dependencies ───────────────────────────────────────────────
    deps = raw.get("dependencies")
    if deps is not None:
        if not isinstance(deps, list):
            violations.append("'dependencies' must be a list of strings when present")
        elif not all(isinstance(d, str) for d in deps):
            violations.append("'dependencies' entries must all be strings")

    # ── Optional: env ────────────────────────────────────────────────────────
    env = raw.get("env")
    if env is not None:
        if not isinstance(env, dict):
            violations.append("'env' must be a dict when present")
        elif not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
            violations.append("'env' keys and values must all be strings")

    # ── Optional: capabilities ───────────────────────────────────────────────
    caps = raw.get("capabilities")
    if caps is not None and not isinstance(caps, dict):
        violations.append("'capabilities' must be a dict when present")

    # ── Raise on violations ──────────────────────────────────────────────────
    if violations:
        raise MCPAddonContractError(violations, name=name)

    return MCPAddonContract.from_dict(raw)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def is_valid_mcp_addon_contract(raw: Dict[str, Any]) -> bool:
    """Return ``True`` if *raw* passes :func:`validate_mcp_addon_contract`.

    Never raises; validation errors are logged at DEBUG level.
    """
    try:
        validate_mcp_addon_contract(raw)
        return True
    except (MCPAddonContractError, TypeError) as exc:
        logger.debug("MCPAddonContract validation failed: %s", exc)
        return False


def build_mcp_addon_contract_summary(contract: MCPAddonContract) -> Dict[str, Any]:
    """Return a compact summary dict for observability / logging."""
    return {
        "name": contract.name,
        "schema_version": contract.schema_version,
        "protocol": contract.protocol,
        "transport": contract.transport,
        "entrypoint": contract.entrypoint,
        "has_dependencies": bool(contract.dependencies),
        "dependency_count": len(contract.dependencies),
        "has_env": bool(contract.env),
        "has_capabilities": bool(contract.capabilities),
        "version": contract.version,
        "author": contract.author,
        "repository": contract.repository,
    }
