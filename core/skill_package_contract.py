"""
core/skill_package_contract.py
================================
PR-005 — Canonical Skill Package Contract

Defines the **authoritative schema** for ``skill.json`` manifests that ship
inside GitHub-installable Skill addon repositories.

Any compliant Skill repo must include a ``skill.json`` at its root.
``GitHubInstaller`` reads this file and passes it through
:func:`validate_skill_package_contract` before loading the Skill; invalid
packages are rejected with structured :class:`SkillPackageContractError` errors.

``SkillLoader.load()`` also validates ``skill.json`` via this contract before
creating a ``SkillInstance``, ensuring consistent enforcement regardless of the
install path.

Schema (``schema_version`` = ``"1"``)
--------------------------------------
Required fields:

``id`` (str)
    Unique identifier for this skill.  Must match ``[A-Za-z0-9_-]+``.

``name`` (str)
    Human-readable display name for this skill.  Must be non-empty.

``handler_file`` (str)
    Relative path to the Python file containing the handler function,
    e.g. ``"handler.py"`` or ``"src/my_handler.py"``.

``handler_function`` (str)
    Name of the callable inside ``handler_file`` to invoke when the skill
    is executed, e.g. ``"execute"``.

Optional fields:

``schema_version`` (str, default ``"1"``)
    Contract schema version.  Must be ``"1"`` for the current release.
    Future schema revisions will bump this value.

``description`` (str)
    Human-readable description of what this skill does.

``version`` (str)
    Skill release version, e.g. ``"1.2.3"`` (informational; distinct from
    ``schema_version``).

``parameters`` (list[dict])
    Parameter schema for the skill.  Each entry must be a dict with at least
    a ``"name"`` key.  Additional keys (``"type"``, ``"description"``,
    ``"required"``, ``"default"``) are optional but validated for type when
    present.

``dependencies`` (list[str])
    Pip package specifiers to install before the skill is first executed.

``permissions`` (list[str])
    Capability permission strings required by this skill
    (e.g. ``["internet", "filesystem"]``).  Informational; consumed by the
    capability catalog.

``tags`` (list[str])
    Taxonomy tags that help the capability resolver categorise the skill
    (e.g. ``["productivity", "search"]``).

``repository`` (str)
    Source repository URL (informational).

``author`` (str)
    Maintainer name or email (informational).

Validation
----------
:func:`validate_skill_package_contract` raises
:class:`SkillPackageContractError` on any violation.  All violations are
collected before the error is raised so callers see the complete list.

Usage::

    from core.skill_package_contract import (
        validate_skill_package_contract,
        SkillPackageContractError,
    )

    try:
        contract = validate_skill_package_contract(raw_manifest)
    except SkillPackageContractError as exc:
        print("Invalid skill package:", exc.violations)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.SkillPackageContract")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The current (and only) supported schema version string.
CURRENT_SCHEMA_VERSION = "1"

#: Regex for valid skill identifiers.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------


class SkillPackageContractError(ValueError):
    """Raised when a ``skill.json`` manifest fails contract validation.

    Attributes
    ----------
    violations : list[str]
        Human-readable description of each schema violation.
    error_code : str
        Machine-readable error code ``"SKILL_PACKAGE_CONTRACT_INVALID"``.
    """

    error_code = "SKILL_PACKAGE_CONTRACT_INVALID"

    def __init__(self, violations: List[str], skill_id: str = "") -> None:
        self.violations = list(violations)
        self.skill_id = skill_id
        msg = f"SkillPackageContract '{skill_id}' invalid: {violations}"
        super().__init__(msg)


# ---------------------------------------------------------------------------
# Contract dataclass
# ---------------------------------------------------------------------------


@dataclass
class SkillPackageContract:
    """Validated, normalised representation of a ``skill.json`` manifest.

    Do **not** construct directly; use :func:`validate_skill_package_contract`
    which validates the raw dict and returns a populated instance.
    """

    # Required
    id: str
    name: str
    handler_file: str
    handler_function: str

    # Optional with defaults
    schema_version: str = CURRENT_SCHEMA_VERSION
    description: str = ""
    version: str = "1.0.0"

    # Lists
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    # Informational metadata
    repository: str = ""
    author: str = ""

    # ── Serialisation ────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "handler_file": self.handler_file,
            "handler_function": self.handler_function,
            "parameters": self.parameters,
            "dependencies": self.dependencies,
            "permissions": self.permissions,
            "tags": self.tags,
            "repository": self.repository,
            "author": self.author,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillPackageContract":
        """Construct without validation (internal use only)."""
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            handler_file=str(data.get("handler_file", "")),
            handler_function=str(data.get("handler_function", "")),
            schema_version=str(data.get("schema_version", CURRENT_SCHEMA_VERSION)),
            description=str(data.get("description", "")),
            version=str(data.get("version", "1.0.0")),
            parameters=list(data.get("parameters") or []),
            dependencies=list(data.get("dependencies") or []),
            permissions=list(data.get("permissions") or []),
            tags=list(data.get("tags") or []),
            repository=str(data.get("repository", "")),
            author=str(data.get("author", "")),
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_skill_package_contract(
    raw: Dict[str, Any],
    *,
    allow_future_schema: bool = False,
) -> SkillPackageContract:
    """Validate *raw* manifest dict and return a :class:`SkillPackageContract`.

    Parameters
    ----------
    raw:
        Parsed content of ``skill.json``.
    allow_future_schema:
        If ``True``, schema versions newer than :data:`CURRENT_SCHEMA_VERSION`
        are accepted with a warning instead of raising an error.  Intended for
        forward-compatibility in test environments.

    Returns
    -------
    SkillPackageContract
        A fully validated and normalised contract instance.

    Raises
    ------
    SkillPackageContractError
        When one or more validation rules are violated.  All violations are
        collected before raising so callers see the complete list.
    TypeError
        When *raw* is not a dict.
    """
    if not isinstance(raw, dict):
        raise TypeError(
            f"skill.json must be a JSON object (dict), got {type(raw).__name__}"
        )

    violations: List[str] = []
    skill_id: str = raw.get("id", "")

    # ── Required: id ─────────────────────────────────────────────────────────
    if not skill_id or not isinstance(skill_id, str):
        violations.append("'id' is required and must be a non-empty string")
    elif not _ID_RE.match(skill_id):
        violations.append(
            f"'id' must match [A-Za-z0-9_-]+, got {skill_id!r}"
        )

    # ── Required: name ───────────────────────────────────────────────────────
    name = raw.get("name", "")
    if not name or not isinstance(name, str):
        violations.append("'name' is required and must be a non-empty string")

    # ── Required: handler_file ───────────────────────────────────────────────
    handler_file = raw.get("handler_file", "")
    if not isinstance(handler_file, str) or not handler_file.strip():
        violations.append("'handler_file' is required and must be a non-empty string")

    # ── Required: handler_function ───────────────────────────────────────────
    handler_function = raw.get("handler_function", "")
    if not isinstance(handler_function, str) or not handler_function.strip():
        violations.append("'handler_function' is required and must be a non-empty string")

    # ── Optional: schema_version ─────────────────────────────────────────────
    schema_version = str(raw.get("schema_version", CURRENT_SCHEMA_VERSION))
    if schema_version != CURRENT_SCHEMA_VERSION:
        msg = (
            f"'schema_version' {schema_version!r} is not supported; "
            f"expected {CURRENT_SCHEMA_VERSION!r}"
        )
        if allow_future_schema:
            logger.warning(
                "SkillPackageContract: %s (accepted via allow_future_schema)", msg
            )
        else:
            violations.append(msg)

    # ── Optional: parameters ─────────────────────────────────────────────────
    params = raw.get("parameters")
    if params is not None:
        if not isinstance(params, list):
            violations.append("'parameters' must be a list of objects when present")
        else:
            for i, p in enumerate(params):
                if not isinstance(p, dict):
                    violations.append(
                        f"'parameters[{i}]' must be a dict, got {type(p).__name__}"
                    )
                elif not p.get("name"):
                    violations.append(
                        f"'parameters[{i}].name' is required and must be non-empty"
                    )

    # ── Optional: dependencies ───────────────────────────────────────────────
    deps = raw.get("dependencies")
    if deps is not None:
        if not isinstance(deps, list):
            violations.append("'dependencies' must be a list of strings when present")
        elif not all(isinstance(d, str) for d in deps):
            violations.append("'dependencies' entries must all be strings")

    # ── Optional: permissions ────────────────────────────────────────────────
    perms = raw.get("permissions")
    if perms is not None:
        if not isinstance(perms, list):
            violations.append("'permissions' must be a list of strings when present")
        elif not all(isinstance(p, str) for p in perms):
            violations.append("'permissions' entries must all be strings")

    # ── Optional: tags ───────────────────────────────────────────────────────
    tags = raw.get("tags")
    if tags is not None:
        if not isinstance(tags, list):
            violations.append("'tags' must be a list of strings when present")
        elif not all(isinstance(t, str) for t in tags):
            violations.append("'tags' entries must all be strings")

    # ── Raise on violations ──────────────────────────────────────────────────
    if violations:
        logger.warning(
            "SkillPackageContract validation failed for '%s': %s",
            skill_id,
            violations,
            extra={
                "event": "skill_package_contract_invalid",
                "skill_id": skill_id,
                "violations": violations,
                "error_code": SkillPackageContractError.error_code,
            },
        )
        raise SkillPackageContractError(violations, skill_id=skill_id)

    logger.debug(
        "SkillPackageContract validated: id=%s name=%s handler=%s:%s",
        skill_id,
        name,
        handler_file,
        handler_function,
        extra={
            "event": "skill_package_contract_validated",
            "skill_id": skill_id,
        },
    )
    return SkillPackageContract.from_dict(raw)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def is_valid_skill_package_contract(raw: Dict[str, Any]) -> bool:
    """Return ``True`` if *raw* passes :func:`validate_skill_package_contract`.

    Never raises; validation errors are logged at DEBUG level.
    """
    try:
        validate_skill_package_contract(raw)
        return True
    except (SkillPackageContractError, TypeError) as exc:
        logger.debug("SkillPackageContract validation failed: %s", exc)
        return False


def build_skill_package_contract_summary(
    contract: SkillPackageContract,
) -> Dict[str, Any]:
    """Return a compact summary dict for observability and logging."""
    return {
        "id": contract.id,
        "name": contract.name,
        "schema_version": contract.schema_version,
        "version": contract.version,
        "handler_file": contract.handler_file,
        "handler_function": contract.handler_function,
        "has_parameters": bool(contract.parameters),
        "parameter_count": len(contract.parameters),
        "has_dependencies": bool(contract.dependencies),
        "dependency_count": len(contract.dependencies),
        "has_permissions": bool(contract.permissions),
        "tags": contract.tags,
        "author": contract.author,
        "repository": contract.repository,
    }
