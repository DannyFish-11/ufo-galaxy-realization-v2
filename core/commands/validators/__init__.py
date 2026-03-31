"""
core/commands/validators — Command Validation Subpackage
=========================================================

**Batch PR-5: Command routing decomposition**

This sub-package provides the ``CommandValidator`` abstract base class and
built-in validators for the command routing layer.

Authority sentinel
------------------
``COMMAND_VALIDATOR_AUTHORITY = "core.commands.validators"``

Built-in validators
-------------------
``EnvelopeValidator``
    Validates that a command envelope has all required non-empty fields
    (delegating to ``validate_command_envelope`` in ``core.command_router``).

``RiskClassificationValidator``
    Rejects high-risk commands unless an explicit override is present in the
    context metadata (``allow_high_risk=True``).

Usage::

    from core.commands.validators import EnvelopeValidator, RiskClassificationValidator

    validator = EnvelopeValidator()
    validator.validate(device_id="phone-1", command="screenshot", ...)
"""
from __future__ import annotations

import abc
import logging
from typing import Any, Dict, Optional, Set

from core.command_router import (
    GatewayError,
    GatewayErrorCode,
    validate_command_envelope,
)

logger = logging.getLogger("Galaxy.Commands.Validators")

# ── sub-package authority sentinel ────────────────────────────────────────
COMMAND_VALIDATOR_AUTHORITY: str = "core.commands.validators"
"""Sentinel: core.commands.validators is the canonical command validation module.

Import this symbol to assert that a call site is using the decomposed
validator sub-package.
"""

# ── high-risk commands (mirrors CommandRouter._HIGH_RISK_COMMANDS) ────────
_HIGH_RISK_COMMANDS: frozenset = frozenset({
    "delete", "format", "shutdown", "reboot", "wipe",
    "rm", "remove", "purge", "factory_reset",
    "execute_shell", "run_script", "sudo",
    "transfer_funds", "payment", "checkout",
    "drone_takeoff", "arm_system",
    "system_change", "registry_write",
})


class ValidationError(Exception):
    """Raised when a command fails validation."""

    def __init__(self, message: str, error_code: str = "VALIDATION_ERROR") -> None:
        super().__init__(message)
        self.error_code = error_code

    def to_dict(self) -> Dict[str, Any]:
        return {"error": True, "error_code": self.error_code, "message": str(self)}


class CommandValidator(abc.ABC):
    """Abstract base class for command validators.

    Subclasses must implement :meth:`validate`.  Validators are stateless
    and may be re-used across requests.
    """

    @abc.abstractmethod
    def validate(
        self,
        command: str,
        *,
        device_id: str = "",
        payload: Optional[Dict[str, Any]] = None,
        command_id: str = "",
        task_id: str = "",
        context_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Validate the command.

        Raises
        ------
        ValidationError:
            If the command fails validation.
        """


class EnvelopeValidator(CommandValidator):
    """Validates command envelope completeness.

    Delegates to :func:`~core.command_router.validate_command_envelope`.
    """

    def validate(
        self,
        command: str,
        *,
        device_id: str = "",
        payload: Optional[Dict[str, Any]] = None,
        command_id: str = "",
        task_id: str = "",
        context_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            validate_command_envelope(
                device_id=device_id,
                command=command,
                payload=payload or {},
                command_id=command_id or "validate",
                task_id=task_id or "validate",
            )
        except GatewayError as exc:
            raise ValidationError(str(exc), error_code=exc.code.value) from exc


class RiskClassificationValidator(CommandValidator):
    """Rejects high-risk commands unless explicitly allowed.

    A command is allowed if:
    - It is not in the high-risk set, OR
    - ``context_metadata.get("allow_high_risk")`` is ``True``.
    """

    def __init__(self, high_risk_commands: Optional[Set[str]] = None) -> None:
        self._high_risk = frozenset(high_risk_commands or _HIGH_RISK_COMMANDS)

    def validate(
        self,
        command: str,
        *,
        device_id: str = "",
        payload: Optional[Dict[str, Any]] = None,
        command_id: str = "",
        task_id: str = "",
        context_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        meta = context_metadata or {}
        if command in self._high_risk and not meta.get("allow_high_risk"):
            raise ValidationError(
                f"Command '{command}' is classified as high-risk and requires "
                "explicit approval (set allow_high_risk=True in context metadata).",
                error_code="HIGH_RISK_COMMAND",
            )


__all__ = [
    "COMMAND_VALIDATOR_AUTHORITY",
    "CommandValidator",
    "EnvelopeValidator",
    "RiskClassificationValidator",
    "ValidationError",
]
